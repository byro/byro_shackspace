from os import path

from django.conf import settings
from django.core.management import BaseCommand
from django.db.models import Q
from django.template.loader import get_template
from django.utils import timezone


class Command(BaseCommand):

    def handle(self, *args, **options):
        from byro_shackspace.models import ShackProfile

        profiles = ShackProfile.objects.filter(
            member__memberships__end__isnull=True,
            is_keyholder=True,
        ).order_by('member__number')

        for task in ["open", "close"]:
            context = {
                'task': task,
                'profiles': [
                    {
                        'name': profile.member.name,
                        'number': profile.member.number,
                        'nick': profile.member.profile_profile.nick,
                        'key': profile.ssh_public_key,
                    }
                    for profile in profiles
                ],
            }
            content = get_template('shackspace/portal_authorized_keys.txt').render(context)

            with open(path.join(settings.BASE_DIR, f'authorized_keys.{task}'), 'w') as f:
                f.write(content)
