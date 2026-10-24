# A release: the fork image plus its skills and manifest (context = a skill-stage output folder).
ARG PLATFORM
FROM iqraa/platform:${PLATFORM}
COPY skills/ /app/skill/
ENV DEPLOYMENT_SKILLS_DIR=/app/skill
