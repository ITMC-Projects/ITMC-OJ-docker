FROM itmc-oj-prod/base:local

ENTRYPOINT ["celery", "-A", "dmoj_celery", "worker", "-l", "info", "--concurrency=2"]


COPY repo/ /site/
WORKDIR /site
RUN django-admin compilemessages
