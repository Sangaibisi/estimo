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

{{- define "estimo.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ .Values.serviceAccount.name | default (printf "%s" .Release.Name) }}
{{- else -}}
{{ .Values.serviceAccount.name | default "default" }}
{{- end -}}
{{- end -}}

{{/*
Secret references that carry credentials into the pod environment. The chart's own
Secret holds non-credential config; anything sensitive (gateway API key, a full
database URL with a password) comes from a Secret the operator created out-of-band,
so it never passes through values.yaml or `helm get values`.
*/}}
{{- define "estimo.envFrom" -}}
- secretRef:
    name: {{ .Release.Name }}-env
{{- with .Values.gateway.existingSecret }}
- secretRef:
    name: {{ . }}
{{- end }}
{{- with .Values.database.existingSecret }}
- secretRef:
    name: {{ . }}
{{- end }}
{{- end -}}

{{/*
The repos working tree is a single ReadWriteOnce claim shared by every API pod, so
more than one replica only schedules if the storage class is ReadWriteMany. Fail the
install loudly rather than leaving the operator with a Pod stuck Pending forever.
*/}}
{{- define "estimo.validate" -}}
{{- if and (gt (int .Values.api.replicas) 1) (ne .Values.api.reposStorage.accessMode "ReadWriteMany") -}}
{{- fail "api.replicas > 1 requires api.reposStorage.accessMode=ReadWriteMany (the git working tree is a shared volume); set replicas to 1 or use an RWX storage class" -}}
{{- end -}}
{{- end -}}
