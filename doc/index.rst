Account Reports
###############

Reports in Account.

PDF generation
==============

PDF reports use FPDF2 directly, backported from version 8.0, with bundled
DejaVu Sans fonts for Unicode text. Install the ``fpdf2 >= 2.8, < 3`` dependency
and update the module to load the revised views and translations. The report
wizards offer PDF and Excel output.

The timeout covers both data preparation and PDF generation. An explicit report
timeout or the accounting configuration's default timeout takes precedence.
Otherwise the Journal allows 600 seconds and the shared PDF generator allows
300 seconds. Large annual journals may require a higher configured timeout,
depending on the server and data volume.
