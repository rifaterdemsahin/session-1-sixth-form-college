FROM nginx:1.27-alpine
COPY index.html PLAN.md /usr/share/nginx/html/
EXPOSE 80
