# agenda-clinica (molde sistema-web, apps/factory/bin/sistema_novo.py, com volume de dados).
# Base por digest (a mesma de apps/sites/Dockerfile), só biblioteca padrão, processo sem root
# (uid 10001, o mesmo do manifest do k3s) e raiz só leitura: o app escreve apenas em /data.
FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 DATA_DIR=/data
WORKDIR /app
COPY *.py ./
RUN mkdir /data && chown 10001 /data
USER 10001
VOLUME /data
EXPOSE 8080
CMD ["python3", "app.py"]
