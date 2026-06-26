{{- define "app.name" -}}
{{- default .Chart.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "app.fullname" -}}
{{- default .Release.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "app.labels" -}}
app.kubernetes.io/name: {{ include "app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Build "registry/<repository>:<tag>" for a component.
     Usage: {{ include "app.image" (dict "root" $ "component" "backend") }} */}}
{{- define "app.image" -}}
{{- $img := index .root.Values.image .component -}}
{{- printf "%s/%s:%s" .root.Values.image.registry $img.repository $img.tag -}}
{{- end -}}
