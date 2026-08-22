import base64
import os
import uuid
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

from tempfile import NamedTemporaryFile
from typing import List, Optional, Dict, Annotated, BinaryIO, Union

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption, PowerpointFormatOption, \
    ExcelFormatOption
from docling_core.types.doc import ImageRefMode
from fastapi import UploadFile
from langchain_core.document_loaders import BaseLoader

from langchain_community.document_loaders import UnstructuredMarkdownLoader, UnstructuredCSVLoader, \
    TextLoader, UnstructuredXMLLoader, JSONLoader
from starlette.datastructures import Headers

from ChatMe.ChatService.FilesLoaders.config import FILE_ALLOWED_TYPES, TEXT_TRUNCATE_LENGTH
from ChatMe.ChatService.FilesLoaders.SofficeConverter import get_converter, LibreOfficeNotFoundError
from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.ChatMeConfig.core import get_oss_config
from ChatMe.paths import CACHED_DIR


def _upload_local_image_to_oss(local_path: str, original_filename: str = None) -> Optional[str]:
    """
    上传本地图片到 OSS，返回 OSS URL

    Args:
        local_path: 本地文件路径（如 ~/.../Image_10.png）
        original_filename: 原始文件名，用于生成 OSS key

    Returns:
        OSS URL 字符串，失败返回 None
    """
    try:
        import oss2

        oss_cfg = get_oss_config()
        access_key_id = oss_cfg.get("access_key_id")
        access_key_secret = oss_cfg.get("access_key_secret")
        bucket_name = oss_cfg.get("bucket")
        endpoint = oss_cfg.get("endpoint")

        if not all([access_key_id, access_key_secret, bucket_name, endpoint]):
            logger = get_logger("FilesLoaders")
            logger.warning(f"OSS 配置不完整，跳过上传: {local_path}")
            return None

        # 生成 OSS key：chatme/{年份月份}/{uuid}_{原文件名}
        date_prefix = datetime.now().strftime("%Y-%m")
        filename = original_filename or os.path.basename(local_path)
        oss_key = f"chatme/{date_prefix}/{uuid.uuid4().hex[:4]}_{filename}"

        # 上传到 OSS
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        bucket.put_object_from_file(oss_key, local_path)

        # 返回 OSS URL
        oss_url = f"https://{bucket_name}.{endpoint.replace('https://', '')}/{oss_key}"
        logger = get_logger("FilesLoaders")
        logger.info(f"文件上传 OSS 成功: {local_path} -> {oss_url}")
        return oss_url

    except ImportError:
        logger = get_logger("FilesLoaders")
        logger.warning(f"oss2 模块未安装，无法上传到 OSS: {local_path}")
        return None
    except Exception as e:
        logger = get_logger("FilesLoaders")
        logger.warning(f"上传图片到 OSS 失败: {local_path}, 错误: {e}")
        return None

class UploadFileWithId(UploadFile):
    """
    继承UploadFile，给每个文件添加唯一的file_id字段

    使用方式：
    - 在文件上传处理时，将普通 UploadFile 转换为 UploadFileWithId
    - 或者直接使用 UploadFileWithId 替代 UploadFile

    特性：
    - 保留所有 UploadFile 的原有功能（read, write, seek, close 等）
    - 自动在初始化时生成唯一的 file_id
    - 可通过 file.file_id 属性访问
    """
    def __init__(
        self,
        file: BinaryIO,
        *,
        size: int | None = None,
        filename: str | None = None,
        headers: Headers | None = None,
    ) -> None:
        super().__init__(file=file, size=size, filename=filename, headers=headers)
        self.file_id = str(f"file_{uuid.uuid4().hex[:4]}")

    async def read(self, size: int = -1) -> bytes:
        """重写 read 方法，保持父类功能"""
        return await super().read(size)

    async def seek(self, offset: int) -> None:
        """重写 seek 方法，保持父类功能"""
        return await super().seek(offset)

    async def write(self, data: bytes) -> None:
        """重写 write 方法，保持父类功能"""
        return await super().write(data)

    async def close(self) -> None:
        """重写 close 方法，保持父类功能"""
        return await super().close()

@dataclass
class OutputFormat:
    # === 内容字段（用于 AI 处理 / message_stream）===
    text_content: Annotated[Optional[str], "文本文件内容"] = None
    image_content: Annotated[Optional[Union[str, List[str]]], "图片 base64 或文档图片列表"] = None

    # === OSS 标识 ===
    is_oss: Annotated[bool, "文档图片是否已上传 OSS（markdown 中已包含 URL，不再传图片）"] = False

    # === 文件标识 ===
    file_id: Annotated[Optional[str], "文件唯一ID"] = None
    file_path: Annotated[Optional[str], "缓存文件路径"] = None

    # === 前端显示字段 ===
    name: Annotated[Optional[str], "文件名"] = None
    type: Annotated[Optional[str], "文件类型 IMAGE/TEXT/DOCUMENT"] = None
    content_type: Annotated[Optional[str], "MIME type"] = None
    size: Annotated[int, "文件大小字节"] = 0
    size_human: Annotated[Optional[str], "人类可读文件大小"] = None

    # === 预览字段 ===
    preview: Annotated[Optional[str], "预览 URL (data: 或 http:)"] = None
    iframe_url: Annotated[Optional[str], "iframe 预览 URL"] = None
    content: Annotated[Optional[str], "文本文件内容（前端直接显示）"] = None

    # === 预览控制 ===
    is_previewable: Annotated[bool, "是否可预览"] = True
    preview_method: Annotated[Optional[str], "预览方式 iframe/iframe_office/download"] = None
    preview_hint: Annotated[Optional[str], "预览提示"] = None

    # === 下载支持 ===
    suffix: Annotated[Optional[str], "文件后缀"] = None

class FilesLoaders:

    def __init__(self, processing_files: Optional[list[UploadFileWithId]], session_id: str):
        self.session_id = session_id
        self.logger = get_logger("FilesLoader")
        self.processing_files = processing_files
        self.processing_dir = CACHED_DIR / session_id

        os.makedirs(self.processing_dir, exist_ok=True)

    async def cleanup(self):
        """异步清理资源"""
        if self.processing_files:
            for file in self.processing_files:
                await file.close()
            self.processing_files = None
            self.logger.debug("文件资源已清理")

    @staticmethod
    async def _get_file_suffix(filename: Optional[str]) -> str:
        """
        提取文件后缀，处理边界情况：
        1. 无后缀（如"readme"）返回空字符串
        2. 多后缀（如"file.tar.gz"）返回最后一个后缀（.gz）
        3. 后缀转小写（如".PNG"→".png"）
        """
        if not filename or "." not in filename:
            return ""
        return "." + filename.split(".")[-1].lower()

    @staticmethod
    async def _switch_suffix_to_file_type(suffix: str) -> str:
        """
        将文件类型转换为相应的后缀
        Args:
            suffix: 文件类型
        Returns:
            文件后缀
        """
        return suffix.replace(".", "")

    @staticmethod
    def _maybe_truncate(file_text: str, file_path: Optional[str], max_chars: int) -> str:
        """
        大文件按行截断，仅保留完整行

        - 未超过 max_chars：原样返回
        - 超过：按行累加，截断到 max_chars 以内，并在顶部加截断提示
        - 提示里附带 file_path，便于 AI 在分析时直接使用，或通过环境探索读全量

        Args:
            file_text: 已加载好的文本内容
            file_path: 文件缓存路径（用于提示）
            max_chars: 字符数上限

        Returns:
            截断后的文本
        """
        if not file_text or len(file_text) <= max_chars:
            return file_text

        lines = file_text.split('\n')
        total_lines = len(lines)

        kept_lines: list[str] = []
        current_chars = 0
        for line in lines:
            # +1 是把分隔符 \n 算回去，最后一行不加
            line_len = len(line) + (1 if len(kept_lines) < total_lines - 1 else 0)
            if current_chars + line_len > max_chars:
                break
            kept_lines.append(line)
            current_chars += line_len

        # 边缘情况：单行就超限 → 硬截到头部
        if not kept_lines and lines:
            kept_lines = [lines[0][:200]]
            total_lines = 1

        kept_count = len(kept_lines)
        hint = (
            f"[文件过大已截断] \n"
            f"[完整文件路径] {os.path.relpath(file_path) if file_path else '未知'}\n"
            f"[提示] 如需分析完整文件内容，请进行文件所在环境探索\n\n"
        )
        return hint + '\n'.join(kept_lines)

    async def _classifying_files(self):
        files = self.processing_files
        images, texts, documents = [], [], []

        if files:
            for file in files:
                suffix = await FilesLoaders._get_file_suffix(file.filename)
                if suffix in FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_SUFFIX"]:
                    images.append(file)
                elif suffix in FILE_ALLOWED_TYPES["TEXT"]["TEXT_SUFFIX"]:
                    texts.append(file)
                elif suffix in FILE_ALLOWED_TYPES["DOCUMENT"]["DOCUMENT_SUFFIX"]:
                    documents.append(file)

        return images, texts, documents

    async def _create_temp_file_path(self, file: UploadFileWithId, suffix: str) -> Optional[str]:
        """
        将 UploadFile 写入临时文件，返回临时文件的路径字符串（可直接传给 UnstructuredFileLoader）

        Args:
            file: FastAPI 上传的文件对象

        Return
            临时文件的绝对路径
        """
        try:
            file_item = file.file_id.replace("file", f"{file.filename}")
            temp_file_dir = Path(self.processing_dir) / file_item
            os.makedirs(temp_file_dir, exist_ok=True)

            # 1. 创建临时文件（suffix 保留原文件后缀，确保 loader 识别格式）
            with NamedTemporaryFile(
                delete=False,
                suffix=suffix,
                prefix=file.filename,
                mode='wb',
                dir=temp_file_dir,
            ) as temp_file:
                # 方式2：分块写入（大文件，避免内存溢出）
                chunk_size = 1024 * 1024  # 1MB/块
                while chunk := await file.read(chunk_size):
                    temp_file.write(chunk)

            # 3. 返回临时文件的绝对路径(.../cached/{文件前缀})
            temp_file_path = os.path.abspath(temp_file.name)
            return temp_file_path

        except Exception as e:
            self.logger.error(f"创建临时文件失败：{str(e)}")
            return None

    async def _process_images(self, files: List[UploadFileWithId]) -> List[OutputFormat]:
        """
        处理传入的图片文件，优先用 OSS URL， fallback 到 base64
        """
        outputs: List[OutputFormat] = []
        self.logger.debug(f"开始处理{len(files)}个图片文件")

        # 检测 OSS 配置
        oss_cfg = get_oss_config()
        use_oss = bool(oss_cfg.get("access_key_id") and oss_cfg.get("bucket"))
        self.logger.debug(f"OSS 配置检测: use_oss={use_oss}, bucket={oss_cfg.get('bucket')}")

        for file in files:
            output = OutputFormat(
                text_content=None,
                image_content="",
            )
            file_path = None
            try:
                suffix = await self._get_file_suffix(file.filename)
                file_path = await self._create_temp_file_path(file, suffix)

                # 获取文件基础信息
                file_kwargs = await self.create_file_additional_kwargs(file, suffix, file_path)

                # 尝试上传 OSS
                if use_oss:
                    oss_url = _upload_local_image_to_oss(file_path, file.filename)
                    if oss_url:
                        output.image_content = oss_url
                        output.is_oss = True
                    else:
                        # OSS 上传失败，用 base64
                        with open(file_path, "rb") as f:
                            image_data = f.read()
                            base64_data = base64.b64encode(image_data).decode('utf-8')
                        output.image_content = base64_data
                        output.is_oss = False
                else:
                    # 未配置 OSS，用 base64
                    with open(file_path, "rb") as f:
                        image_data = f.read()
                        base64_data = base64.b64encode(image_data).decode('utf-8')
                    output.image_content = base64_data
                    output.is_oss = False

                # 直接设置 OutputFormat 字段
                output.file_id = file_kwargs.file_id
                output.file_path = file_kwargs.file_path
                output.name = file_kwargs.name
                output.type = file_kwargs.type
                output.content_type = file_kwargs.content_type
                output.size = file_kwargs.size
                output.size_human = file_kwargs.size_human
                output.preview = file_kwargs.preview
                output.iframe_url = file_kwargs.iframe_url
                output.is_previewable = file_kwargs.is_previewable
                output.preview_method = file_kwargs.preview_method
                output.preview_hint = file_kwargs.preview_hint
                output.suffix = file_kwargs.suffix

                outputs.append(output)
                self.logger.debug(f"图片处理成功: {file.filename}, is_oss={output.is_oss}")

            except Exception as e:
                self.logger.error(f"处理图片文件失败({file.filename}): {e}")
                outputs.append(output)

        self.logger.debug(f"图片处理完成，成功{sum(1 for o in outputs if o.image_content)}/{len(files)}个")
        return outputs

    async def _process_texts(self, files: List[UploadFileWithId]) -> List[OutputFormat]:
        """
        使用langchain的document_loader组件处理传入文件信息，类型为txt，md等常见文本类型
        :param files:
        :return: text_list
        """
        outputs: List[OutputFormat] = []
        self.logger.debug(f"开始处理{len(files)}个文本文件")

        for file in files:
            output = OutputFormat(
                text_content="",
                image_content=None,
            )
            file_path = None
            try:
                suffix = await self._get_file_suffix(file.filename)
                file_path = await self._create_temp_file_path(file, suffix)

                # 获取文件基础信息
                file_kwargs = await self.create_file_additional_kwargs(file, suffix, file_path)

                loader: Optional[BaseLoader] = None
                if suffix == ".md":
                    loader = UnstructuredMarkdownLoader(file_path, mode="single", strategy="fast")
                elif suffix == ".csv":
                    loader = UnstructuredCSVLoader(file_path=file_path, mode="single", strategy="fast")
                elif suffix == ".txt":
                    loader = TextLoader(file_path=file_path, encoding="utf-8")
                elif suffix == ".xml":
                    loader = UnstructuredXMLLoader(file_path=file_path, mode="single", strategy="fast")
                elif suffix == ".json":
                    loader = JSONLoader(file_path=file_path, jq_schema=".[]", text_content=True)
                else:
                    self.logger.warning(f"不支持的文件类型：{file.filename}")
                    outputs.append(output)
                    continue

                documents = await loader.aload()
                file_text = documents[0].page_content if documents else ""

                # 大文件按行截断，避免全量塞进 LLM prompt
                file_text = self._maybe_truncate(
                    file_text, file_path, TEXT_TRUNCATE_LENGTH
                )

                # 直接设置 OutputFormat 字段
                output.file_id = file_kwargs.file_id
                output.file_path = file_kwargs.file_path
                output.name = file_kwargs.name
                output.type = file_kwargs.type
                output.content_type = file_kwargs.content_type
                output.size = file_kwargs.size
                output.size_human = file_kwargs.size_human
                output.preview = file_kwargs.preview
                output.iframe_url = file_kwargs.iframe_url
                output.is_previewable = file_kwargs.is_previewable
                output.preview_method = file_kwargs.preview_method
                output.preview_hint = file_kwargs.preview_hint
                output.suffix = file_kwargs.suffix
                output.text_content = file_text
                output.content = file_text  # 前端直接显示用
                output.is_oss = False

                outputs.append(output)
                self.logger.debug(f"文本文件处理成功: {file.filename}({len(file_text)}字符)")

            except Exception as e:
                self.logger.error(f"处理文本文件失败({file.filename}): {e}")
                outputs.append(output)

        self.logger.debug(f"文本文件处理完成，成功{sum(1 for o in outputs if o.text_content)}/{len(files)}个")
        return outputs

    async def _process_documents(self, files: List[UploadFileWithId])->  List[OutputFormat]:
        """
            使用docling处理文档

            Args:
                files: 前端传入文档文件

            Return
                处理好的文档的markdown文件(包含图片结构)的数组
        """

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_table_structure = True  # 启用表格结构识别
        pipeline_options.generate_page_images = True  # 生成页面图片
        pipeline_options.generate_picture_images = True  # 提取文档中的图片
        pipeline_options.images_scale = 1.0  # 图片缩放比例，提高质量
        pipeline_options.do_ocr = False  # ❌ 不启用 OCR，避免下载模型

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                InputFormat.DOCX: WordFormatOption(),
                InputFormat.PPTX: PowerpointFormatOption(),
                InputFormat.XLSX: ExcelFormatOption(),
            }
        )

        outputs: List[OutputFormat] = []
        self.logger.debug(f"开始处理{len(files)}个文档")

        for file in files:
            output = OutputFormat(text_content="", image_content=[])
            file_path = None
            try:
                suffix = await self._get_file_suffix(file.filename)
                file_path = await self._create_temp_file_path(file, suffix)

                # 转换旧版 Office 格式 (.doc/.ppt/.xls → .docx/.pptx/.xlsx)
                soffice_converter = get_converter()
                if soffice_converter.can_convert(suffix):
                    try:
                        file_path = soffice_converter.convert(file_path)
                        suffix = soffice_converter.get_target_suffix(suffix)
                    except LibreOfficeNotFoundError:
                        self.logger.warning(f"LibreOffice 未安装，跳过文件: {file.filename}")
                        outputs.append(output)
                        continue
                    except Exception as e:
                        self.logger.warning(f"soffice 转换失败，跳过文件 {file.filename}: {e}")
                        outputs.append(output)
                        continue

                # 获取文件基础信息
                file_kwargs = await self.create_file_additional_kwargs(file, suffix, file_path)

                result = converter.convert(file_path)
                doc = result.document

                output_dir = Path(file_path).parent / f"{file.file_id}_output"
                output_dir.mkdir(exist_ok=True)
                output_path = output_dir / "document.md"
                doc.save_as_markdown(output_path, image_mode=ImageRefMode.REFERENCED)

                ads_prefix = str(output_dir) + '/'
                rel_prefix = "./"
                with open(output_path, 'rb') as f:
                    raw_data = f.read(2000)
                    import chardet
                    result = chardet.detect(raw_data)
                    detected_encoding = result.get("encoding", "utf-8")

                temp_path = output_path.with_suffix(".md.tmp")
                with open(output_path, "r", encoding=detected_encoding) as f_in, \
                        open(temp_path, "w", encoding=detected_encoding) as f_out:
                    for i, line in enumerate(f_in):
                        if line.startswith("!["):
                            img_pattern = r'!\[(.*?)\]\(([^)]+)\)'
                            if match := re.search(img_pattern, line):
                                prefix_name = match.group(1)
                                new_name = f"{prefix_name}_{i}.png"
                                match_dir = match.group(2)
                                dir_with_new_name = f"{output_dir}/document_artifacts/{new_name}"
                                os.rename(match_dir, dir_with_new_name)
                                line = line.replace(match_dir, dir_with_new_name)
                                line = line.replace(ads_prefix, rel_prefix)

                                # 尝试上传 OSS
                                oss_url = _upload_local_image_to_oss(dir_with_new_name, new_name)
                                if oss_url:
                                    # OSS 上传成功，用 OSS URL
                                    line = line.replace(f"./document_artifacts/{new_name}", oss_url)
                                    output.image_content.append(oss_url)
                                    output.is_oss = True
                                else:
                                    output.is_oss = False
                                    # OSS 上传失败，用 base64
                                    with open(dir_with_new_name, "rb") as f:
                                        image_content = f.read()
                                        base64_data = base64.b64encode(image_content).decode("utf-8")
                                        output.image_content.append(base64_data)

                        f_out.write(line)
                    temp_path.replace(output_path)

                file_content = output_path.read_text(encoding=detected_encoding)

                # 大文件按行截断，避免全量塞进 LLM prompt
                file_content = self._maybe_truncate(
                    file_content, file_path, TEXT_TRUNCATE_LENGTH
                )

                # 直接设置 OutputFormat 字段
                output.file_id = file_kwargs.file_id
                output.file_path = file_kwargs.file_path
                output.name = file_kwargs.name
                output.type = file_kwargs.type
                output.content_type = file_kwargs.content_type
                output.size = file_kwargs.size
                output.size_human = file_kwargs.size_human
                output.preview = file_kwargs.preview
                output.iframe_url = file_kwargs.iframe_url
                output.is_previewable = file_kwargs.is_previewable
                output.preview_method = file_kwargs.preview_method
                output.preview_hint = file_kwargs.preview_hint
                output.suffix = file_kwargs.suffix
                output.text_content = file_content
                output.content = file_content  # 前端直接显示用

                outputs.append(output)
                self.logger.debug(f"文档处理成功: {file.filename}({len(file_content)}字符)")

            except Exception as e:
                self.logger.error(f"文档处理失败({file.filename}): {e}")
                outputs.append(output)

        self.logger.debug(f"文档处理完成，成功{sum(1 for o in outputs if o.text_content)}/{len(files)}个")
        return outputs

    async def loading_files(self) -> Optional[List[OutputFormat]]:
        """
        处理传入文件信息，返回处理好的二进制文件内容
        :return: images_content（含图片信息列表）, text_content（含文本信息列表）
        """
        (images, texts, docs) = await self._classifying_files()

        outputs: List[OutputFormat] = []
        images_outputs = await self._process_images(images)
        texts_outputs = await self._process_texts(texts)
        docs_outputs = await self._process_documents(docs)

        outputs.extend(images_outputs)
        outputs.extend(texts_outputs)
        outputs.extend(docs_outputs)

        return outputs if outputs else []

    async def create_file_additional_kwargs(self, file: UploadFileWithId, suffix: str, file_path: str) -> OutputFormat:
        """
        创建用于前端预览的文件信息

        Returns:
            OutputFormat: 包含文件预览信息的对象，支持 iframe 直接预览
        """
        if not file:
            return OutputFormat()

        await file.seek(0)
        file_content = await file.read()
        file_size = len(file_content)
        base64_content = base64.b64encode(file_content).decode("utf-8")

        file_type_category = self._get_file_type_category(suffix)

        preview_info = self._get_preview_info(file_type_category, suffix)

        return OutputFormat(
            file_id=file.file_id,
            file_path=file_path,
            name=file.filename,
            type=file_type_category,
            content_type=file.content_type,
            size=file_size,
            size_human=self._format_file_size(file_size),
            preview=f"data:{file.content_type};base64,{base64_content}",
            iframe_url=self._get_iframe_url(file_type_category, suffix, file.content_type, base64_content),
            is_previewable=preview_info["is_previewable"],
            preview_method=preview_info["preview_method"],
            preview_hint=preview_info["preview_hint"],
            suffix=suffix,
        )

    @staticmethod
    def _get_file_type_category(suffix: str) -> str:
        """
        根据文件后缀判断文件类型分类

        Args:
            suffix: 文件后缀（如 .png, .txt）

        Returns:
            str: 文件类型分类 (image/text/document)
        """
        suffix = suffix.lower()

        if suffix in FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_SUFFIX"]:
            return "IMAGE"
        elif suffix in FILE_ALLOWED_TYPES["TEXT"]["TEXT_SUFFIX"]:
            return "TEXT"
        elif suffix in FILE_ALLOWED_TYPES["DOCUMENT"]["DOCUMENT_SUFFIX"]:
            return "DOCUMENT"
        else:
            return "UNKNOWN"

    @staticmethod
    def _get_iframe_url(file_type: str, suffix: str, content_type: str, base64_content: str) -> str:
        """
        生成可用于 iframe src 的 URL

        Args:
            file_type: 文件类型分类
            suffix: 文件后缀
            content_type: MIME 类型
            base64_content: base64 编码的文件内容

        Returns:
            str: 可用于 iframe 的 URL
        """
        suffix = suffix.lower()

        if file_type == "IMAGE":
            return f"data:{content_type};base64,{base64_content}"

        elif file_type == "TEXT":
            return f"data:{content_type};base64,{base64_content}"

        elif file_type == "DOCUMENT":
            if suffix == ".pdf":
                return f"data:{content_type};base64,{base64_content}"
            elif suffix in [".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"]:
                return f"data:{content_type};base64,{base64_content}"
            else:
                return ""

        return ""

    @staticmethod
    def _get_preview_info(file_type: str, suffix: str) -> Dict:
        """
        根据文件类型获取预览信息

        Args:
            file_type: 文件类型分类
            suffix: 文件后缀

        Returns:
            Dict: 包含预览相关信息的字典
        """
        suffix = suffix.lower()

        if file_type == "IMAGE":
            return {
                "is_previewable": True,
                "preview_method": "iframe",
                "preview_hint": "可在 iframe 中直接预览图片"
            }
        elif file_type == "TEXT":
            return {
                "is_previewable": True,
                "preview_method": "iframe",
                "preview_hint": "可在 iframe 中直接显示文本内容"
            }
        elif file_type == "DOCUMENT":
            if suffix == ".pdf":
                return {
                    "is_previewable": True,
                    "preview_method": "iframe",
                    "preview_hint": "可在 iframe 中直接预览 PDF（浏览器原生支持）"
                }
            elif suffix in [".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"]:
                return {
                    "is_previewable": True,
                    "preview_method": "iframe_office",
                    "preview_hint": "可在 iframe 中使用 base64 预览，或建议上传后使用 Office Online Viewer"
                }
            else:
                return {
                    "is_previewable": False,
                    "preview_method": "download",
                    "preview_hint": "不支持在线预览，请下载后查看"
                }
        else:
            return {
                "is_previewable": False,
                "preview_method": "download",
                "preview_hint": "不支持在线预览，请下载后查看"
            }

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """
        格式化文件大小为人类可读格式

        Args:
            size_bytes: 文件大小（字节）

        Returns:
            str: 格式化后的大小（如 "1.5 MB"）
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
