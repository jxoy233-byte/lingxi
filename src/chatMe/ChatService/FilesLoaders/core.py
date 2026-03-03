import base64
import logging
import os

from tempfile import NamedTemporaryFile
from typing import List, Optional, Dict

from fastapi import UploadFile, HTTPException
from langchain_core.document_loaders import BaseLoader

from chatMe.ChatService import FILE_ALLOWED_TYPES
from langchain_community.document_loaders import UnstructuredMarkdownLoader, UnstructuredCSVLoader, \
    TextLoader, UnstructuredXMLLoader, JSONLoader


class FilesLoaders:
    def __init__(self, processing_files :list[UploadFile] | None):
        self.processing_files = processing_files

    async def cleanup(self):
        """异步清理资源"""
        if self.processing_files:
            for file in self.processing_files:
                await file.close()
            self.processing_files = None

    async def _get_file_suffix(self, filename: Optional[str]) -> str:
        """
        提取文件后缀，处理边界情况：
        1. 无后缀（如"readme"）返回空字符串
        2. 多后缀（如"file.tar.gz"）返回最后一个后缀（.gz）
        3. 后缀转小写（如".PNG"→".png"）
        """
        if not filename or "." not in filename:
            return ""
        return "." + filename.split(".")[-1].lower()

    async def _distinguish_files(self, files: List[UploadFile]):
        """
        划分文件类型
        :param files:
        :return: images, texts(图片类型， 文本类型)
        """
        if not files:
            logging.warning("未传入任何图片文件，返回空二进制数据")
            return None,None

        images_type = FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_SUFFIX"]
        texts_type = FILE_ALLOWED_TYPES["TEXT"]["TEXT_SUFFIX"]
        images, texts= [], []
        for file in files:
            file_name = file.filename or "不支持文件或位置文件"
            file_suffix = await self._get_file_suffix(file_name)
            if file_suffix in images_type:
                images.append(file)
            elif file_suffix in texts_type:
                texts.append(file)
            else:
                # 宽松处理，防止影响后续文件处理
                logging.warning(f"忽略不支持的文件类型：{file_name}")
                await file.close()  # 单独关闭非法文件，释放资源
                continue  # 跳过当前文件，处理下一个

        # 后续还要进行文件操作，不要关闭文件
        return images, texts

    async def _process_files_img(self, files: List[UploadFile])-> Optional[List[Dict]]:
        """
        处理传入图片类型文件信息，类型为png，jpg等常见图片类型
        :param files:
        :return:
        """
        # 将多个图片文件处理进入同一份二进制数据
        images_list: Optional[List[Dict]] = []
        if not files:
            logging.info("未传入任何图片文件，返回空二进制数据")
            return None

        for img in files:
            image_byte = await img.read()
            if not image_byte: # 过滤为空图片
                logging.warning(f"图片文件{img.filename}为空，跳过")
                await img.close()
                continue

            image_dict ={
                "file_content": base64.b64encode(image_byte).decode("utf-8"),
                "file_name": img.filename,
                "file_type": await self._get_file_suffix(img.filename),
                "file_size": img.size,
            }
            # 拼接URL时，bytes与str无法直接拼接
            images_list.append(image_dict)
            logging.info(f"成功读取图片{img.filename}，大小：{img.size/1024:.2f}KB")

        return images_list

    async def _create_temp_file_path(self, file: UploadFile, suffix: str) -> str:
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
                # 2. 将 UploadFile 内容写入临时文件
                ##  方式1：直接读取二进制写入（小文件）
                # shutil.copyfileobj(file.file, temp_file)
                # 方式2：分块写入（大文件，避免内存溢出）
                chunk_size = 1024 * 1024  # 1MB/块
                while chunk := await file.read(chunk_size):
                    temp_file.write(chunk)

            # 3. 返回临时文件的绝对路径（字符串格式，也可返回 Path 对象）
            temp_file_path = os.path.abspath(temp_file.name)
            return temp_file_path

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"创建临时文件失败：{str(e)}")

    async def _process_files_text(self, files: List[UploadFile])-> Optional[List[Dict]]:
        """
        使用langchain的document_loader组件处理传入文件信息，类型为txt，md等常见文本类型
        :param files:
        :return:
        """

        if not files:
            logging.info("未传入任何文本文件，返回空二进制数据")
            return None

        text_list: Optional[List[Dict]] = []
        for file in files:
            temp_file_path = None
            try:
                text_suffix = await self._get_file_suffix(file.filename)
                temp_file_path = await self._create_temp_file_path(file, text_suffix)
                loader :BaseLoader
                """
                将 UploadFile 的内容写入本地临时文件；
                传入 UnstructuredFileLoader；
                解析完成后删除临时文件（避免占用磁盘）。
                """
                ...
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
                file_name = file.filename
                file_dict = {
                    "file_content": file_text,
                    "file_name": file_name,
                    "file_suffix": text_suffix,
                    "file_size": file.size,
                }
                text_list.append(file_dict)

            except Exception as e:
                logging.error(f"处理文件 {file.filename} 失败：{str(e)}")
                text_list.append({})  # 保证列表完整性
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                        logging.info(f"成功删除临时文件：{temp_file_path}")
                    except Exception as e:
                        logging.error(f"删除临时文件失败：{temp_file_path}，错误信息：{str(e)}")

        return text_list if text_list else None


    async def loading_files(self):
        """
        处理传入文件信息，返回处理好的二进制文件内容
        :param files:
        :return: images_content（含图片信息列表）, text_content（含文本信息列表）
        """
        files = self.processing_files

        Images, Texts = await self._distinguish_files(files=files)

        images_content :Optional[List[Dict]] = await self._process_files_img(Images)
        text_content :Optional[List[Dict]] = await self._process_files_text(Texts)

        return images_content, text_content

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


