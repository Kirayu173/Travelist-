"""Production-data smoke tests.

These tests are intentionally kept outside `backend/tests` so they do NOT inherit
the test DB fixtures that clone/migrate a dedicated *_test database.

Run explicitly:
  `pytest backend/prod_tests -q`
"""
