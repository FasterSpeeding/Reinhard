FROM registry.access.redhat.com/ubi9/python-312@sha256:d1244378f7ab72506d8d91cadebbf94c893c2828300f9d44aee4678efec62db9 AS install

WORKDIR /code

COPY ./pyproject.toml ./
COPY ./uv.lock ./

RUN pip install uv && \
    uv sync --frozen --only-group main

FROM install AS gen_ref_indexes

WORKDIR /code

COPY ./scripts/gen_ref_index.py ./gen_ref_index.py

RUN uv sync --frozen --group references && \
    /code/venv/bin/python ./gen_ref_index.py default --out-dir ./indexes

FROM registry.access.redhat.com/ubi9/python-312@sha256:1d8846b7c6558a50b434f1ea76131f200dcdd92cfaf16b81996003b14657b491

WORKDIR /reinhard

COPY --from=gen_ref_indexes /code/indexes ./indexes
COPY --from=install /code/.venv ./venv
COPY ./reinhard ./reinhard
COPY ./main.py ./main.py

ENV REINHARD_INDEX_DIR=/reinhard/indexes
ENTRYPOINT ["./venv/bin/python", "-O", "main.py"]
