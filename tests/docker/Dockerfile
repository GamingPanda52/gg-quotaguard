FROM python:3.13-slim
WORKDIR /app
COPY gg_quotaguard.py /app/gg_quotaguard.py
COPY tests /app/tests
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
