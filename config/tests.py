from django.test import TestCase
from django.urls import reverse


class SiteTests(TestCase):
    def test_root_redirects_to_docs(self):
        response = self.client.get("/")
        self.assertRedirects(response, reverse("swagger-ui"), fetch_redirect_response=False)
        self.assertEqual(response.status_code, 302)

    def test_docs_include_instructions_and_token_autofill(self):
        response = self.client.get(reverse("swagger-ui"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ui.preauthorizeApiKey("jwtAuth"')

        schema = self.client.get(reverse("schema"), {"format": "json"}).json()
        self.assertIn("Как попробовать", schema["info"]["description"])
