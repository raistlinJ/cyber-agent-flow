FROM python:3.12-slim
LABEL io.cyber-agent-flow.managed="tool-tests"
COPY runner.py suite.py /runner/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python3", "/runner/runner.py"]
