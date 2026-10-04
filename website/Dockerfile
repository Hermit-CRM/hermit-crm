# Serve the built site/ folder as a static site on Fly.
#
# The page is self-contained (no web fonts, no analytics, no trackers), so
# nothing here needs network access at runtime.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/

# /data is where fly.toml mounts the volume that holds the download log. Making
# it here lets nginx start without the volume, and `nginx -t` fails the build
# on a config mistake instead of deploying a site that will not start.
RUN mkdir -p /data && nginx -t

EXPOSE 80
