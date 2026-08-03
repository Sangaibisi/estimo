{{- define "estimo.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "estimo.labels" -}}
app.kubernetes.io/name: estimo
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "estimo.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion -}}
{{- end -}}

{{/*
The URL the API connects with. Multi-tenant deployments MUST set database.url to the
NOSUPERUSER estimo_app role (a superuser bypasses RLS — ADR-0007). Bundled mode
defaults to the owner (fine for single-tenant). $(POSTGRES_PASSWORD) is substituted
from the pod env.
*/}}
{{- define "estimo.apiDatabaseUrl" -}}
{{- if .Values.database.url -}}
{{ .Values.database.url }}
{{- else if .Values.postgres.bundled -}}
postgresql+asyncpg://{{ .Values.postgres.auth.username }}:$(POSTGRES_PASSWORD)@{{ .Release.Name }}-postgres:5432/{{ .Values.postgres.auth.database }}
{{- end -}}
{{- end -}}

{{/*
The URL migrations run with — must be the OWNER (CREATE ROLE / bypass RLS). Defaults to
the bundled owner; override with database.migrationUrl in multi-tenant BYO setups.
*/}}
{{- define "estimo.migrationDatabaseUrl" -}}
{{- if .Values.database.migrationUrl -}}
{{ .Values.database.migrationUrl }}
{{- else if .Values.postgres.bundled -}}
postgresql+asyncpg://{{ .Values.postgres.auth.username }}:$(POSTGRES_PASSWORD)@{{ .Release.Name }}-postgres:5432/{{ .Values.postgres.auth.database }}
{{- else -}}
{{ .Values.database.url }}
{{- end -}}
{{- end -}}
