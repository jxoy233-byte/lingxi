
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
}



