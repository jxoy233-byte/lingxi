
FILE_MAX_LENGTH = 25*1024*1024  # 25MB

FILE_ALLOWED_TYPES = {
    "IMAGE": { # 图片类型 + 图片后缀白名单 + 对应MIME类型
        "IMAGE_TYPE": {"png", "jpg", "jpeg", "gif"},
        "IMAGE_SUFFIX": {".png", ".jpg", ".jpeg", ".gif", },
        "IMAGE_MIME": {"image/png", "image/jpeg", "image/gif", },
    },

    "TEXT": { # 文本类型 + 文本后缀白名单 + 对应MIME类型
        "TEXT_TYPE" : {"txt", "md", "csv", "xml", "json"},
        "TEXT_SUFFIX" : {".txt", ".md", ".csv", ".xml", ".json"},
        "TEXT_MIME" : {"text/plain", "text/markdown", "text/csv", "text/xml", "application/json"},
    },

    "DOCUMENT": {  # 文档类型 + 文档后缀白名单 + 对应 MIME 类型
        "DOCUMENT_TYPE": {"pdf", "docx", "pptx", "xlsx"},
        "DOCUMENT_SUFFIX": {".pdf", ".docx", ".pptx", ".xlsx"},
        "DOCUMENT_MIME": {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        },
    },
}



