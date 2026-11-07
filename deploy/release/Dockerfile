# A release: the fork image plus its skills and manifest (context = a skill-stage output folder).
# It runs as node (O-40). Root keeps the code and the skills; node owns only the folders LibreChat writes to:
# uploads and generated images (api/config/paths.js) and the winston logs (api/logs, from the cwd /app/api).
# The platform image already makes /app/data 1777. Named volumes mounted on these folders take this ownership on
# first mount. PLATFORM_REPO lets a test build on a throwaway platform tag.
ARG PLATFORM
ARG PLATFORM_REPO=iqraa/platform
FROM ${PLATFORM_REPO}:${PLATFORM}
COPY skills/ /app/skill/
ENV DEPLOYMENT_SKILLS_DIR=/app/skill
RUN mkdir -p /app/uploads /app/api/logs /app/client/public/images \
  && chown -R node:node /app/uploads /app/api/logs /app/client/public/images
USER node
