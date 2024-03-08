FROM python:3.12.2
WORKDIR /reinhard

COPY ./reinhard ./reinhard
COPY ./dev-requirements/constraints.txt ./requirements.txt
COPY ./main.py ./main.py

ENV DOCKER_DEBUG=false
RUN python -m pip install --no-cache-dir wheel && \
    python -m pip install --no-cache-dir -r requirements.txt

ENTRYPOINT if ${DOCKER_DEBUG} == false; then python main.py; else python -O main.py; fi
