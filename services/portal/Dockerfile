FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production

COPY package*.json ./

RUN npm ci

COPY src ./src
COPY views ./views

RUN chgrp -R 0 /app && chmod -R g=u /app

USER 1001

EXPOSE 3000

CMD ["npm", "start"]
