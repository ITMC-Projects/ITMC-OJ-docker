FROM itmc-oj-prod/base:local

EXPOSE 9999
EXPOSE 9998

ENTRYPOINT ["python3", "manage.py", "runbridged"]


COPY repo/ /site/
WORKDIR /site
RUN django-admin compilemessages
