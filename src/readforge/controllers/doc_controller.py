# extended functions for api endpoints

from copy import Error
from re import escape

from fastapi import requests, responses
from fastapi.responses import Response
from readforge.utils.reading_util import (
    is_file_exist,
    create_presigned_url,
    submit_ocr_batch,
)
from pydantic import BaseModel, ConfigDict, Field


class UploadDocRequest(BaseModel):
    file_name: str
    # put check the key shouldn't be more then 20 bytes | char
    idem_key: str


class UploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)  # forbid unexpected fields
    success: bool
    message: str
    job_id: str | None


async def upload_doc(request: UploadDocRequest) -> UploadResponse:
    # read file name from the request
    file_name = request.file_name

    # check if the file exists in the db
    # if exists_response false send error back
    exists_response = await is_file_exist(file_name)

    if exists_response is False:
        # create instance of Upload response with error
        # return error with status code
        return

    # get presigned url
    signed_url = create_presigned_url(file_name)

    # call the redis function for job creation

    # if job creation failed :
    # create instance of Upload response with error

    # create instance of Upload response with success
    # send response
