
FILE_MAX_LENGTH = 10*1024*1024

FILE_ALLOWED_TYPES = {
    "IMAGE": { # 图片后缀白名单 + 对应MIME类型
        "IMAGE_SUFFIX": {".png", ".jpg", ".jpeg", ".gif", },
        "IMAGE_MIME": {"image/png", "image/jpeg", "image/gif", },
    },

    "TEXT": { # 文后缀白名单 + 对应MIME类型
        "TEXT_SUFFIX" : {".txt", ".md", ".csv", ".xml", ".json"},
        "TEXT_MIME" : {"text/plain", "text/markdown", "text/csv", "text/xml", "application/json"},
    },

    "DOCUMENT": {  # 文档后缀白名单 + 对应MIME类型
        "DOCUMENT_SUFFIX": {
            # 办公文档
            ".docx", ".doc",  # Word
            # 便携文档
            ".pdf",
        },
        "DOCUMENT_MIME": {
            # Excel MIME 类型
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
            "application/vnd.ms-excel",  # xls
            # Word MIME 类型
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
            "application/msword",  # doc
            # PowerPoint MIME 类型
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
            "application/vnd.ms-powerpoint",  # ppt
            # PDF MIME 类型
            "application/pdf",
            # 补充其他常见文档 MIME 类型（可选）
            "application/rtf",
            "application/vnd.oasis.opendocument.text",  # odt
            "application/vnd.oasis.opendocument.spreadsheet",  # ods
            "application/vnd.oasis.opendocument.presentation",  # odp
        },
    },
}



