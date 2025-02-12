import json

from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from app.models import HomepageImage

class Command(BaseCommand):
    help = 'Import the home page guide pictures into the database from static/assets/img/guidepics/redirect.json'

    def handle(self, *args, **kwargs):
        guide_pic_dir = 'static/assets/img/guidepics'
        with open(f'{guide_pic_dir}/redirect.json') as f:
            a = json.load(f)
        with transaction.atomic():
            for (i, (name, url)) in enumerate(a.items()):
                with open(f'{guide_pic_dir}/{name}', 'rb') as f:
                    # Django file
                    df = File(f)
                    df.name = name
                    HomepageImage.objects.create(
                        redirect_url = url, image = df, description = f'Image {i}',
                        sort_id = i, activated = True
                    )
                print(f'Uploaded {name}, redirecting to "{url}"')
