from readforge.utils.redis_utils import fetch_jobs, send_to_dead_letter_queue

# function : extend main worker function

# number of jobs fetch at a time
JOB_COUNT = 10


def main() -> None:
    while True:
        # fetch job from redis
        jobs_vec = fetch_jobs(JOB_COUNT)

        # if unable to fetch job
        if jobs_vec is None:
            break

        # download a load pdf into memory if the pdf is less then 50 mb
        # if more then 50 mb load  certain pages of that pdf first into memory then execute

        # call the ocr function from the utility
