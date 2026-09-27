# extended functions for api endpoints

from copy import Error
from re import escape

from fastapi import requests, responses
from pydantic import BaseModel
from fastapi.responses import Response
from readforge.utils.reading_util import (
    is_file_exist,
    create_presigned_url,
    submit_ocr_batch,
)


class UploadDocRequest(BaseModel):
    file_name: str
    idem_key: str


class UploadResponseError(BaseModel):
    success: bool
    message: str


async def upload_doc(request: UploadDocRequest) -> Response:
    # read file name from the request
    file_name = request.file_name

    # check if the file exists in the db
    # if exists_response false send error back
    exists_response = await is_file_exist(file_name)
    if exists_response is False:
        return Response

    # get presigned url
    signed_url = create_presigned_url(file_name)

    # call the redis function
