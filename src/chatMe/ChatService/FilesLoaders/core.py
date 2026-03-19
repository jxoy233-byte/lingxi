import base64
import logging
import os
import subprocess
from pathlib import Path

from tempfile import NamedTemporaryFile
from typing import List, Optional, Dict, Annotated

import fitz
import pandas as pd
from docx import Document, ImagePart
from fastapi import UploadFile, HTTPException
from langchain_core.document_loaders import BaseLoader

from chatMe.ChatService import FILE_ALLOWED_TYPES
from langchain_community.document_loaders import UnstructuredMarkdownLoader, UnstructuredCSVLoader, \
    TextLoader, UnstructuredXMLLoader, JSONLoader, UnstructuredWordDocumentLoader, PyMuPDFLoader


class FilesLoaders:
    output_kwargs: Annotated[
        Optional[List[Dict]],
        "有文件传输时带字段file_name,file_type,file_size,file_content,传输失败则增加error字段"
    ]

    def __init__(self, processing_files :list[UploadFile] | None):
        self.processing_files = processing_files

    async def cleanup(self):
        """异步清理资源"""
        if self.processing_files:
            for file in self.processing_files:
                await file.close()
            self.processing_files = None

    @classmethod
    async def _get_file_suffix(cls, filename: Optional[str]) -> str:
        """
        提取文件后缀，处理边界情况：
        1. 无后缀（如"readme"）返回空字符串
        2. 多后缀（如"file.tar.gz"）返回最后一个后缀（.gz）
        3. 后缀转小写（如".PNG"→".png"）
        """
        if not filename or "." not in filename:
            return ""
        return "." + filename.split(".")[-1].lower()

    async def _distinguish_files(self):
        """
        划分文件类型
        :param
        :return: images, texts, docs(图片类型， 文本类型, 文档类型)
        """
        files = self.processing_files

        if not files:
            logging.warning("未传入任何图片文件，返回空二进制数据")
            return None,None,None

        images_type = FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_SUFFIX"]
        texts_type = FILE_ALLOWED_TYPES["TEXT"]["TEXT_SUFFIX"]
        docs_type = FILE_ALLOWED_TYPES["DOCUMENT"]["DOCUMENT_SUFFIX"]
        images, texts, docs= [], [], []
        for file in files:
            file_name = file.filename or "不支持文件或位置文件"
            file_suffix = await self._get_file_suffix(file_name)
            if file_suffix in images_type:
                images.append(file)
            elif file_suffix in texts_type:
                texts.append(file)
            elif file_suffix in docs_type:
                docs.append(file)
            else:
                # 宽松处理，防止影响后续文件处理
                logging.warning(f"忽略不支持的文件类型：{file_name}")
                await file.close()  # 单独关闭非法文件，释放资源
                continue  # 跳过当前文件，处理下一个

        # 后续还要进行文件操作，不要关闭文件
        return images, texts, docs

    @classmethod
    async def _process_files_img(cls, files: List[UploadFile])-> Optional[List[Dict]]:
        """
        处理传入图片类型文件信息，类型为png，jpg等常见图片类型
        :param files:
        :return: image_list
        """
        # 将多个图片文件处理进入同一份二进制数据
        images_list: Optional[List[Dict]] = []
        if not files:
            logging.info("未传入任何图片文件，返回空二进制数据")
            return None

        for img in files:
            image_dict = {
                "file_name": img.filename,
                "file_type": await FilesLoaders._get_file_suffix(img.filename),
                "file_size": img.size,
                "file_content": {"text": None, "images": ""}
            }
            image_byte = await img.read()
            if not image_byte: # 过滤为空图片
                logging.warning(f"图片文件{img.filename}为空，跳过")
                await img.close()
                continue

            image_dict["file_content"]["images"] = base64.b64encode(image_byte).decode("utf-8")

            # 拼接URL时，bytes与str无法直接拼接
            images_list.append(image_dict)
            logging.info(f"成功读取图片{img.filename}，大小：{img.size/1024:.2f}KB")

        return images_list

    @classmethod
    async def _create_temp_file_path(cls, file: UploadFile, suffix: str) -> str:
        """
        将 UploadFile 写入临时文件，返回临时文件的路径字符串（可直接传给 UnstructuredFileLoader）
        :param upload_file: FastAPI 上传的文件对象
        :return: 临时文件的绝对路径（如 /tmp/tmpXXXXXX.pdf）
        """
        try:
            # 1. 创建临时文件（suffix 保留原文件后缀，确保 loader 识别格式）
            with NamedTemporaryFile(
                delete=False, # delete=False 表示不自动删除，解析完成后手动清理
                suffix=suffix,
                mode='wb',
            ) as temp_file:
                # 方式2：分块写入（大文件，避免内存溢出）
                chunk_size = 1024 * 1024  # 1MB/块
                while chunk := await file.read(chunk_size):
                    temp_file.write(chunk)

            # 3. 返回临时文件的绝对路径（C:\Users\Administrator\AppData\Local\Temp）
            temp_file_path = os.path.abspath(temp_file.name)
            return temp_file_path

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"创建临时文件失败：{str(e)}")

    @classmethod
    async def _process_files_text(cls, files: List[UploadFile])-> Optional[List[Dict]]:
        """
        使用langchain的document_loader组件处理传入文件信息，类型为txt，md等常见文本类型
        :param files:
        :return: text_list
        """

        if not files:
            logging.info("未传入任何文本文件，返回空二进制数据")
            return None

        text_list: Optional[List[Dict]] = []
        for file in files:
            temp_file_path = None
            file_dict = {
                "file_name": "",
                "file_type": "",
                "file_content": {"text": "", "images": None}
            }
            try:
                text_suffix = await FilesLoaders._get_file_suffix(file.filename)
                temp_file_path = await FilesLoaders._create_temp_file_path(file, text_suffix)

                file_dict["file_name"] = file.filename
                file_dict["file_type"] = text_suffix

                loader: Optional[BaseLoader] = None
                """
                将 UploadFile 的内容写入本地临时文件；
                传入 UnstructuredFileLoader；
                解析完成后删除临时文件（避免占用磁盘）。
                """
                if text_suffix == ".md":
                    loader = UnstructuredMarkdownLoader(
                        temp_file_path,
                        mode="single",
                        strategy="fast",
                    )
                elif text_suffix == ".csv":
                    loader = UnstructuredCSVLoader(
                        file_path = temp_file_path,
                        mode="single",
                        strategy="fast",
                    )
                elif text_suffix == ".txt":
                    loader = TextLoader(
                        file_path = temp_file_path,
                        encoding="utf-8"  # 指定编码
                    )
                elif text_suffix == ".xml":
                    loader = UnstructuredXMLLoader(
                        file_path = temp_file_path,
                        mode="single",
                        strategy="fast",
                    )
                elif text_suffix == ".json":
                    loader = JSONLoader(
                        file_path = temp_file_path,
                        jq_schema=".[]",  # 解析所有数组元素，可根据需求调整
                        text_content=True  # False：保留原始JSON结构，True：仅提取文本
                    )
                else:
                    logging.warning(f"不支持的文件类型：{file.filename}")

                # loader都为BaseLoader的子类 ，都有aload方法可以调用
                documents = await loader.aload()
                file_text = documents[0].page_content if documents else ""
                file_dict["file_content"]["text"] = file_text
                text_list.append(file_dict)

            except Exception as e:
                logging.error(f"处理文件 {file.filename} 失败：{str(e)}")
                text_list.append(file_dict)  # 保证列表完整性
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                        logging.info(f"成功删除临时文件：{temp_file_path}")
                    except Exception as e:
                        logging.error(f"删除临时文件失败：{temp_file_path}，错误信息：{str(e)}")

        return text_list if text_list else None

    @classmethod
    async def process_pptx(cls, pptx_path, dpi=72):
        """
        PPTX → LibreOffice 转 PDF → PyMuPDF 转图片（每一个幻灯片为一个图片）
        :return result字典：具有status,type,page_images.page_info[],page_count参数
        """
        tmpdir = os.path.abspath(os.path.join(pptx_path, '..'))

        output_dir = os.path.join(tmpdir, Path(pptx_path).stem)
        os.makedirs(output_dir, exist_ok=True)

        result = {
            "status": "success",
            "type": ".pptx",
            "images": [],
            "page_count": 0,
        }

        try:
            # ========== LibreOffice 转 PDF ==========
            convert_cmd = [
                "soffice",
                "--headless",
                "--convert-to", "pdf",
                "--outdir", tmpdir,
                pptx_path
            ]

            process = subprocess.run(
                convert_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            if process.returncode != 0:
                raise Exception(process.stderr.decode())

            # 生成的 PDF 路径
            pdf_name = Path(pptx_path).stem + ".pdf"
            pdf_path = os.path.join(tmpdir, pdf_name)

            if not os.path.exists(pdf_path):
                raise Exception("LibreOffice 未生成 PDF")

            # ========== PDF 转图片 ==========
            doc = fitz.open(pdf_path)
            result["page_count"] = len(doc)

            for i in range(len(doc)):
                page = doc.load_page(i)
                pix = page.get_pixmap(dpi=dpi)

                img_blob: bytes = pix.tobytes("png")

                # output_file = os.path.join(output_dir, f"slide_{i + 1}.png")
                img_base64 = base64.b64encode(img_blob).decode()
                result["images"].append(img_base64)

                logging.info(f"{pdf_name} 的 第{i + 1}页已存储")

            doc.close()

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logging.error(f"❌ 转换失败: {str(e)}")

        return result

    @classmethod
    async def extract_docx_images(cls, docx_path):
        """DOCX仅提取图片"""
        result = {
            "status": "success",
            "type": ".docx",
            "images": [],
            "image_info": [],
            "image_count": 0,
        }
        try:
            doc = Document(docx_path)
            images = []  # 图片二进制流列表（用于传输）
            image_info = []

            for idx, rel in enumerate(doc.part.rels.values()):
                if isinstance(rel.target_part, ImagePart):
                    img_blob: bytes = rel.target_part.blob

                    img_base64 = base64.b64encode(img_blob).decode()
                    images.append(img_base64)
                    image_info.append({
                        "size": len(img_blob),
                        "format": rel.target_ref.split('.')[-1].lower() if '.' in rel.target_ref else 'png'
                    })

            result["images"] = images
            result["image_info"] = image_info
            result["image_count"] = len(images)

        except Exception as e:
            logging.error(f"❌ 提取图片失败: {str(e)}")
            result["status"] = "failed"
            result["error"] = str(e)

        return result

    @classmethod
    async def process_pdf(cls, pdf_path, dpi=72):
        """
        PDF → PyMuPDF 转图片（每一个页为图片）
        :return result字典：具有status,type,page_images.page_info[],page_count参数
        """

        result = {
            "status": "success",
            "type": ".pdf",
            "images": [],
            "page_count": 0,
        }

        try:
            pdf_name = Path(pdf_path).stem + ".pdf"
            # ========== PDF 转图片 ==========
            doc = fitz.open(pdf_path)
            result["page_count"] = len(doc)

            for i in range(len(doc)):
                page = doc.load_page(i)
                pix = page.get_pixmap(dpi=dpi)

                img_blob: bytes = pix.tobytes("png")

                # output_file = os.path.join(output_dir, f"slide_{i + 1}.png")
                img_base64 = base64.b64encode(img_blob).decode()
                result["images"].append(img_base64)

                logging.info(f"{pdf_name} 的 第{i + 1}页已存储")

            doc.close()

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logging.error(f"❌ 转换失败: {str(e)}")

        return result

    @classmethod
    async def process_excel(cls, excel_path):
        """
        excel -> 数据清洗 -> DataFrame -> Markdown
        :return: 返回以markdown语法存储的处理好的execl数据
        """
        result = {
            "status": "success",
            "type": ".xlsx",
        }

        try:
            df = pd.read_excel(
                excel_path,
                engine="openpyxl",
                dtype = str,  # 统一读取为字符串
            )
            df = df.dropna(how="all",axis=0)
            df = df.dropna(how="all",axis=1)

            result["content"] = df.to_markdown()

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logging.error(f"❌ 读取excel文件失败: {str(e)}")

        return result

    @classmethod
    async def _process_files_doc(cls, files: List[UploadFile])-> Optional[List[Dict]]:
        """
        使用langchain的document_loader组件以及python其他包处理传入文件信息，类型为xlsx,pdf,pptx,docx等常见文档类型
        :param files:
        :return:
        """
        if not files:
            logging.info("未传入任何文本文件，返回空二进制数据")
            return None

        doc_list: Optional[List[Dict]] = []
        for file in files:
            temp_file_path = None
            file_dict = {
                "file_name": "",
                "file_type": "",
                "file_content": {},
            }
            try:
                doc_suffix = await FilesLoaders._get_file_suffix(file.filename)
                temp_file_path = await FilesLoaders._create_temp_file_path(file, doc_suffix)
                """
                将 UploadFile 的内容写入本地临时文件；
                不同文档类型，进行不同文档解析
                """
                file_dict["file_name"] = file.filename
                file_dict["file_type"] = doc_suffix

                if doc_suffix == ".pptx":
                    result = await FilesLoaders.process_pptx(temp_file_path)
                    if result["status"] == "failed":
                        logging.error(f"pptx文件{file}处理失败, 错误:{result['error']}")
                        raise
                    file_dict["file_content"]["images"] = result["images"]
                    file_dict["file_content"]["text"] = ""
                elif doc_suffix == ".docx":
                    loader = UnstructuredWordDocumentLoader(
                        file_path=temp_file_path,
                        mode="single",
                        strategy="fast",
                    )
                    result = await FilesLoaders.extract_docx_images(temp_file_path)
                    if result["status"] == "failed":
                        logging.error(f"docx文件{file}处理失败, 错误:{result['error']}")
                        raise Exception(result['error'])
                    file_dict["file_content"]["images"] = result["images"]
                    doc = await loader.aload()
                    file_dict["file_content"]["text"] = doc[0].page_content

                elif doc_suffix == ".pdf":
                    result = await FilesLoaders.process_pdf(temp_file_path)
                    if result["status"] == "failed":
                        logging.error(f"pdf文件{file}处理失败, 错误:{result['error']}")
                        raise Exception(result['error'])
                    file_dict["file_content"]["images"] = result["images"]
                    file_dict["file_content"]["text"] = ""

                elif doc_suffix == ".xlsx":
                    result = await FilesLoaders.process_excel(temp_file_path)
                    if result["status"] == "failed":
                        logging.error(f"excel文件{file}处理失败, 错误:{result['error']}")
                        raise Exception(result['error'])
                    file_dict["file_content"]["images"] = []
                    file_dict["file_content"]["text"] = result["content"]

                else:
                    logging.warning(f"不支持的文件类型：{file.filename}")
                    raise Exception(f"不支持的文件类型：{doc_suffix}")


                doc_list.append(file_dict)

            except Exception as e:
                logging.error(f"处理文件 {file.filename} 失败 {str(e)}")
                doc_list.append({})  # 保证列表完整性

            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                        logging.info(f"成功删除临时文件：{temp_file_path}")
                    except Exception as e:
                        logging.error(f"删除临时文件失败：{temp_file_path}，错误信息：{str(e)}")

        return doc_list if doc_list else None

    async def loading_files(self):
        """
        处理传入文件信息，返回处理好的二进制文件内容
        :return: images_content（含图片信息列表）, text_content（含文本信息列表）
        """
        (Images, Texts, Docs) = await self._distinguish_files()

        images_content :Optional[List[Dict]] = await FilesLoaders._process_files_img(Images)
        text_content :Optional[List[Dict]] = await FilesLoaders._process_files_text(Texts)
        doc_content :Optional[List[Dict]] = await FilesLoaders._process_files_doc(Docs)
        # todo 直接添加file_dict字段，使用上面三个content
        return images_content, text_content, doc_content

    async def create_files_additional_kwargs(self)-> List[Dict]:
        files = self.processing_files
        file_list: List[Dict] = [] # 存储前端可响应的记录文件信息的字典列表
        if files:
            for file in files:
                await file.seek(0)

            for file in files:
                file_content = await file.read()
                base64_content = base64.b64encode(file_content).decode("utf-8")
                file_list.append({
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "base64_data": f"data:{file.content_type};base64,{base64_content}"
                })
        else:
            file_list = []

        return file_list


