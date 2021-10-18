# FROM python:3.10.0rc2
FROM colesbury/python-nogil
WORKDIR /reinhard

COPY ./reinhard ./reinhard
COPY ./requirements.txt ./requirements.txt
COPY ./main.py ./main.py

ARG debug=false
ENV DOCKER_DEBUG=${debug}
RUN python -m pip install --upgrade pip wheel
RUN python -m pip install -r requirements.txt

ENTRYPOINT if ${DOCKER_DEBUG} == false; then python main.py; else python -OO main.py; fi
