import base64
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

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
from markdown_it.common.html_re import processing
from multipart import file_path
from starlette.datastructures import Headers

from chatMe.ChatService.FilesLoaders.config import FILE_ALLOWED_TYPES
from chatMe.logging_config import get_logger

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
        self.file_id = str(f"file_{uuid.uuid4().hex[:8]}")

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
    text_content: Annotated[Optional[str], "文件处理过后的返回的相应的文本内容"] = None
    image_content: Annotated[Optional[Union[str,List[dict]]], "文件处理过后的返回的相应的图片内容"] = None
    file_info: Annotated[Optional[dict], "文件处理过后的返回的相应的文件信息"] = None

class FilesLoaders:

    def __init__(self, processing_files :Optional[list[UploadFileWithId]]):
        self.logger = get_logger("FilesLoader")
        self.processing_files = processing_files
        self.processing_dir = str(Path.cwd()) + "/cached"

    async def mkdir(self):
        """创建文件操作目录"""
        os.makedirs(self.processing_dir, exist_ok=True)

    async def cleanup(self):
        """异步清理资源"""
        if self.processing_files:
            for file in self.processing_files:
                await file.close()
            self.processing_files = None

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

    async def _process_images(self, files: List[UploadFileWithId])->  List[OutputFormat]:
        """
        处理传入的图片文件，转化为base64字符串
        """
        outputs: List[OutputFormat] = []

        for file in files:
            output = OutputFormat(
                text_content=None,
                image_content="",
            )
            file_path = None
            try:
                suffix = await self._get_file_suffix(file.filename)
                file_path = await self._create_temp_file_path(file, suffix)

                output.file_info = await self.create_file_additional_kwargs(file, suffix, file_path)
                output.file_type = await self._switch_suffix_to_file_type(suffix)

                with open(file_path, "rb") as f:
                    image_data = f.read()
                    base64_data = base64.b64encode(image_data).decode('utf-8')

                output.image_content = base64_data
                outputs.append(output)

            except Exception as e:
                self.logger.error(f"处理图片文件失败：{str(e)}")
                outputs.append(output)

        return outputs

    async def _process_texts(self, files: List[UploadFileWithId])->  List[OutputFormat]:
        """
        使用langchain的document_loader组件处理传入文件信息，类型为txt，md等常见文本类型
        :param files:
        :return: text_list
        """
        outputs: List[OutputFormat] = []

        for file in files:
            output = OutputFormat(
                text_content="",
                image_content=None,
            )
            file_path = None
            try:
                suffix = await self._get_file_suffix(file.filename)
                file_path = await self._create_temp_file_path(file, suffix)

                output.file_info = await self.create_file_additional_kwargs(file, suffix, file_path)
                output.file_type = await self._switch_suffix_to_file_type(suffix)

                loader: Optional[BaseLoader] = None
                """
                将 UploadFile 的内容写入本地临时文件；
                传入 UnstructuredFileLoader；
                解析完成后删除临时文件（避免占用磁盘）。
                """
                if suffix == ".md":
                    loader = UnstructuredMarkdownLoader(
                        file_path,
                        mode="single",
                        strategy="fast",
                    )
                elif suffix == ".csv":
                    loader = UnstructuredCSVLoader(
                        file_path = file_path,
                        mode="single",
                        strategy="fast",
                    )
                elif suffix == ".txt":
                    loader = TextLoader(
                        file_path = file_path,
                        encoding="utf-8"  # 指定编码
                    )
                elif suffix == ".xml":
                    loader = UnstructuredXMLLoader(
                        file_path = file_path,
                        mode="single",
                        strategy="fast",
                    )
                elif suffix == ".json":
                    loader = JSONLoader(
                        file_path = file_path,
                        jq_schema=".[]",  # 解析所有数组元素，可根据需求调整
                        text_content=True  # False：保留原始JSON结构，True：仅提取文本
                    )
                else:
                    self.logger.warning(f"不支持的文件类型：{file.filename}")

                # loader都为BaseLoader的子类 ，都有aload方法可以调用
                documents = await loader.aload()
                file_text = documents[0].page_content if documents else ""

                output.text_content = file_text
                outputs.append(output)

            except Exception as e:
                self.logger.error(f"处理文件 {file.filename} 失败：{str(e)}")
                outputs.append(output) # 保证列表完整性
            # finally:
            #     if file_path and os.path.exists(file_path):
            #         try:
            #             os.remove(file_path)
            #             self.logger.info(f"成功删除临时文件：{file_path}")
            #         except Exception as e:
            #             self.logger.error(f"删除临时文件失败：{file_path}，错误信息：{str(e)}")

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
        pipeline_options.images_scale = 1.5  # 图片缩放比例，提高质量
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
        for file in files:
            output = OutputFormat(
                text_content = "",
                image_content = "",
            )
            file_path = None
            try:
                suffix = await self._get_file_suffix(file.filename)
                file_path = await self._create_temp_file_path(file, suffix)

                output.file_info = await self.create_file_additional_kwargs(file, suffix, file_path)
                output.file_type = await self._switch_suffix_to_file_type(suffix)

                result = converter.convert(file_path)

                doc = result.document

                output_dir = Path(file_path).parent / f"{Path(file_path).stem}_output"
                output_dir.mkdir(exist_ok=True)

                output_path = output_dir / "document.md"

                doc.save_as_markdown(output_path, image_mode=ImageRefMode.REFERENCED)

                ads_prefix = str(output_dir) + '/'
                rel_prefix = "./"
                with open(output_path, 'rb') as f:
                    raw_data = f.read(10000)
                    import chardet
                    result = chardet.detect(raw_data)
                    detected_encoding = result.get("encoding", "utf-8")

                temp_path = output_path.with_suffix(".md.tmp")
                with open(output_path, "r", encoding=detected_encoding) as f_in, \
                        open(temp_path, "w", encoding=detected_encoding) as f_out:
                    for i, line in enumerate(f_in):
                        if line.startswith("!["):
                            # 修改默认的图片生成名，为了节省tokens
                            import re
                            img_pattern = r'!\[(.*?)\]\(([^)]+)\)'
                            if match := re.search(img_pattern, line):
                                prefix_name = match.group(1)
                                new_name = f"{prefix_name}_{i}.png"

                                match_dir = match.group(2)
                                dir_with_new_name = f"{output_dir}/document_artifacts/{new_name}"
                                os.rename(match_dir, dir_with_new_name)
                                line = line.replace(match_dir, dir_with_new_name)

                                line = line.replace(ads_prefix, rel_prefix)
                        f_out.write(line)
                    temp_path.replace(output_path)

                file_content = output_path.read_text(encoding=detected_encoding)
                output.text_content = file_content

                # 获取可能存在的文件内容
                path = output_dir / "document_artifacts"
                if path.exists():
                    images = []
                    for img in path.iterdir():
                        img_name = img.name

                        img_blob = img.read_bytes()
                        img_base64 = base64.b64encode(img_blob).decode('utf-8')

                        img_dict = {
                            "name": img_name,
                            "base64": img_base64
                        }
                        images.append(img_dict)

                outputs.append(output)

            except Exception as e:
                self.logger.error(f"{file.filename}处理失败: ", str(e))
                outputs.append(output)

        return outputs

    async def loading_files(self)-> Optional[List[OutputFormat]]:
        """
        处理传入文件信息，返回处理好的二进制文件内容
        :return: images_content（含图片信息列表）, text_content（含文本信息列表）
        """
        await self.mkdir()
        (images, texts, docs) = await self._classifying_files()

        outputs: List[OutputFormat] = []
        images_outputs = await self._process_images(images)
        texts_outputs = await self._process_texts(texts)
        docs_outputs = await self._process_documents(docs)

        outputs.extend(images_outputs)
        outputs.extend(texts_outputs)
        outputs.extend(docs_outputs)

        return outputs if outputs else []

    async def create_file_additional_kwargs(self, file: UploadFileWithId, suffix: str, file_path: str)-> dict:
        """
        创建用于前端预览的文件信息列表

        Returns:
            dict: 包含文件预览信息的字典列表，支持 iframe 直接预览
        """
        if not file:
            return {}

        await file.seek(0)
        file_content = await file.read()
        file_size = len(file_content)
        base64_content = base64.b64encode(file_content).decode("utf-8")

        file_type_category = self._get_file_type_category(suffix)

        preview_info = self._get_preview_info(file_type_category, suffix)

        file_info = {
            "file_id": file.file_id,
            "file_name": file.filename,
            "file_path": file_path,
            "file_type": file_type_category,
            "file_size": file_size,
            "file_size_human": self._format_file_size(file_size),
            "preview_url": f"data:{file.content_type};base64,{base64_content}",
            "iframe_url": self._get_iframe_url(file_type_category, suffix, file.content_type, base64_content),
            "is_previewable": preview_info["is_previewable"],
            "preview_method": preview_info["preview_method"],
            "preview_hint": preview_info["preview_hint"],
            "suffix": suffix
        }

        return file_info

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

        if file_type == "image":
            return f"data:{content_type};base64,{base64_content}"

        elif file_type == "text":
            return f"data:{content_type};base64,{base64_content}"

        elif file_type == "document":
            if suffix == ".pdf":
                return f"data:{content_type};base64,{base64_content}"
            elif suffix in [".docx", ".pptx", ".xlsx"]:
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
            elif suffix in [".docx", ".pptx", ".xlsx"]:
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


