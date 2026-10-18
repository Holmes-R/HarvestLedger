"""Validate Indian mobile numbers without silently changing existing contacts."""

import re

from django.core.validators import RegexValidator
from django.db import migrations, models


PHONE_PATTERN = re.compile(r"\A(?:\+91 ?)?[6-9][0-9]{4} ?[0-9]{5}\Z")
OLD_DEMO_PHONES = (
    ("Aarti Bhosale", "0000000001", "9000000001"),
    ("Ganesh Pillai", "0000000002", "9000000002"),
    ("Meera Nair", "0000000003", "9000000003"),
)


def upgrade_demo_phones_and_check_existing(apps, schema_editor):
    Farmer = apps.get_model("procurement", "Farmer")
    farmers = Farmer.objects.using(schema_editor.connection.alias)

    for name, old_phone, new_phone in OLD_DEMO_PHONES:
        farmers.filter(name=name, phone=old_phone).update(phone=new_phone)

    invalid_ids = [
        pk
        for pk, phone in farmers.values_list("pk", "phone").iterator()
        if PHONE_PATTERN.fullmatch(phone) is None
    ]
    if invalid_ids:
        raise RuntimeError(
            "Farmer phone migration stopped: update invalid phone numbers for "
            f"farmer IDs {invalid_ids} before applying this migration."
        )


class Migration(migrations.Migration):
    dependencies = [("procurement", "0001_initial")]

    operations = [
        migrations.RunPython(
            upgrade_demo_phones_and_check_existing,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="farmer",
            name="phone",
            field=models.CharField(
                max_length=16,
                validators=[
                    RegexValidator(
                        regex=r"\A(?:\+91 ?)?[6-9][0-9]{4} ?[0-9]{5}\Z",
                        message=(
                            "Enter a 10-digit Indian mobile number starting with 6, 7, 8, or 9; "
                            "an optional +91 prefix and spaces after the prefix or fifth digit are allowed."
                        ),
                    )
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="farmer",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    phone__regex=r"^(?:\+91 ?)?[6-9][0-9]{4} ?[0-9]{5}$"
                ),
                name="farmer_phone_indian_mobile",
            ),
        ),
    ]
