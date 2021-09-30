FROM python:3.10.0rc2
WORKDIR /reinhard
COPY ./reinhard ./reinhard
COPY ./requirements.txt ./requirements.txt
COPY ./main.py ./main.py
RUN python -m pip install -r requirements.txt
ENTRYPOINT python main.py
