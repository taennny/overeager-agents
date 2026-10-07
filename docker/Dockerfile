FROM python:3.12-slim
RUN mkdir -p /workspace /opt/scope && chown 10001:10001 /workspace
COPY docker/tool_worker.py /opt/scope/tool_worker.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /workspace
VOLUME ["/workspace"]
USER 10001:10001
CMD ["sleep", "infinity"]
