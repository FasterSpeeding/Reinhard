FROM python:3.10.4
# FROM colesbury/python-nogil
WORKDIR /reinhard

COPY ./reinhard ./reinhard
COPY ./requirements.txt ./requirements.txt
COPY ./main.py ./main.py

# Only neccessary if pyjion is also being installed.
# RUN wget https://packages.microsoft.com/config/ubuntu/21.04/packages-microsoft-prod.deb -O packages-microsoft-prod.deb
# RUN dpkg -i packages-microsoft-prod.deb
# RUN rm packages-microsoft-prod.deb
# RUN apt-get update; \
#   apt-get install -y apt-transport-https && \
#   apt-get update && \
#   apt-get install -y aspnetcore-runtime-6.0

ARG debug=false
ENV DOCKER_DEBUG=${debug}
RUN python -m pip install --upgrade pip wheel
RUN python -m pip install -r requirements.txt
# RUN python -m pip install pyjion

ENTRYPOINT if ${DOCKER_DEBUG} == false; then python main.py; else python -OO main.py; fi
