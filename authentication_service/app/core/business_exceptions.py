class BusinessException(Exception):
    def __init__(self, message: str, status_code: int = 400, errors=None):
        self.message = message
        self.status_code = status_code
        self.errors = errors
