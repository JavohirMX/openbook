from rest_framework.exceptions import APIException


class DuplicateISBNError(APIException):
    status_code = 409
    default_detail = "A book with this ISBN already exists."
    default_code = "duplicate_isbn"

    def __init__(self, existing_book_id, detail=None, code=None):
        self.details = {"existing_book_id": str(existing_book_id)}
        super().__init__(detail or self.default_detail, code)
