from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """Wrap successful API responses in the {data, meta} envelope."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return super().render({"data": None}, accepted_media_type, renderer_context)

        if isinstance(data, dict) and ("error" in data or "data" in data):
            return super().render(data, accepted_media_type, renderer_context)

        return super().render({"data": data}, accepted_media_type, renderer_context)
