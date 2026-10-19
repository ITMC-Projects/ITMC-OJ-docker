FROM node:24-alpine

WORKDIR /app
COPY repo/package.json .
COPY repo/package-lock.json .
RUN npm ci

EXPOSE 15100
EXPOSE 15101
EXPOSE 15102

ENTRYPOINT ["node", "/app/site/websocket/daemon.js"]

COPY repo/ /app/site/
