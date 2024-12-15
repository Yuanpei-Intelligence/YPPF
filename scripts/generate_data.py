import os
import sys
import django

sys.path.append(os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'boot.settings')
django.setup()

# STOP SAVING THIS FILE AUTOMATICALLY
# As it will mess up the import list

from app.models import NaturalPerson, User, Organization, OrganizationType
import faker as faker
from faker import Faker
from tqdm import tqdm

USER_COUNT = 200
ORGANIZATION_COUNT = 100
ORGANIZATION_TYPE_COUNT = 10

fk = faker.Faker(locale='zh_CN')
fake = Faker('zh_CN')


def create_fake_user_for_orgnizaiton():
    username = fake.user_name()
    email = fake.email()
    password = fake.password()
    stuid = fake.unique.random_number(digits=8)
    user = User.objects.create_user(
        username=stuid, name=username, email=email, password=password, usertype=User.Type.ORG)
    return user

def create_fake_user_for_natural_person():
    username = fake.user_name()
    email = fake.email()
    password = fake.password()
    stuid = fake.unique.random_number(digits=8)
    user = User.objects.create_user(
        username=stuid, name=username, email=email, password=password, usertype=User.Type.STUDENT)
    return user

def create_fake_natural_person():
    user = create_fake_user_for_natural_person()
    person = NaturalPerson(
        person_id=user,
        name=fake.unique.name(),
        nickname=fake.first_name(),
        gender=fake.random_element(elements=[0, 1]),
        birthday=fake.date_of_birth(),
        email=fake.email(),
        telephone=fake.phone_number(),
        biography=fake.text(max_nb_chars=200),
        inform_share=fake.boolean(),
        last_time_login=fake.date_time_this_year(),
        identity=fake.random_element(elements=[0, 1]),
        stu_class=fake.random_int(min=1, max=5),
        stu_major=fake.text(max_nb_chars=25),
        stu_grade=fake.random_int(min=1, max=5),
        stu_dorm=fake.random_int(min=100, max=999),
        status=0,
        show_nickname=fake.boolean(),
        show_birthday=fake.boolean(),
        show_gender=fake.boolean(),
        show_email=fake.boolean(),
        show_tel=fake.boolean(),
        show_major=fake.boolean(),
        show_dorm=fake.boolean(),
    )
    person.save()


def create_fake_organization_type(n: int):
    otype = OrganizationType(
        otype_id=n,
        otype_name=fake.unique.company(),
    )
    otype.save()


def create_fake_organization():
    user = create_fake_user_for_orgnizaiton()
    organization_type = OrganizationType.objects.get(otype_id=fake.random_int(min=0, max=ORGANIZATION_TYPE_COUNT-1))
    organization = Organization(
        organization_id=user,
        oname=fake.unique.company(),
        otype=organization_type,
    )
    organization.save()

if __name__ == '__main__':
    print('Generating fake data...')
    for i in tqdm(range(ORGANIZATION_TYPE_COUNT), desc='Creating Organization Types'):
        create_fake_organization_type(i)
    actucal_user_count = 0
    for _ in tqdm(range(USER_COUNT), desc='Creating Users'):
        try:
            create_fake_natural_person()
            actucal_user_count += 1
        except Exception as e:
            pass #We don't care about duplicate users
    for _ in tqdm(range(ORGANIZATION_COUNT), desc='Creating Organizations'):
        create_fake_organization()
    print('Done!')
    print(f'Created {actucal_user_count} users, {ORGANIZATION_COUNT} organizations with {ORGANIZATION_TYPE_COUNT} organization types.')
