# Serve the built site/ folder as a static site on Fly.
#
# Staging only for now: nginx.conf keeps this build out of search engines.
# The page is self-contained (no web fonts, no analytics, no trackers), so
# nothing here needs network access at runtime.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/

EXPOSE 80
