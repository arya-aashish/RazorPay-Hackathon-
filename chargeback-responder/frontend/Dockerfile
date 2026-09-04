FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Expose Vite dev server port
EXPOSE 5173

# Run Vite dev server, exposing to local network so Docker can map the port
CMD ["npm", "run", "dev", "--", "--host"]