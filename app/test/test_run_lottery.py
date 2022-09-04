from django.test import TestCase
from app.models import (
    User,
    NaturalPerson,
    Organization,
    OrganizationType,
    Prize,
    Pool,
    PoolItem,
    PoolRecord,
    Notification,
)
from app.YQPoint_utils import run_lottery
from datetime import datetime
from app.constants import YQP_ONAME


class RunLotteryTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        u1 = User.objects.create_user("11", "1", password="111")
        u2 = User.objects.create_user("22", "2", password="222")
        u3 = User.objects.create_user("33", "1", password="333")
        u4 = User.objects.create_user("44", "1", password="333")
        u5 = User.objects.create_user("55", "1", password="333")
        u6 = User.objects.create_user("66", "1", password="333")
        u7 = User.objects.create_user("77", "1", password="333")
        u8 = User.objects.create_user("88", "1", password="333")
        u9 = User.objects.create_user("99", "1", password="333")
        u10 = User.objects.create_user("1010", "1", password="333")

        n1 = NaturalPerson.objects.create(
            person_id=u1, name="1", stu_grade="2018")
        u_YQP = User.objects.create_user("00", "0", password="111")
        otype = OrganizationType.objects.create(
            otype_id=1, otype_name="xxx", incharge=n1)
        Organization.objects.create(
            organization_id=u_YQP, oname=YQP_ONAME, otype=otype)

        prize1 = Prize.objects.create(
            name="明信片", stock=50, reference_price=10)
        prize2 = Prize.objects.create(
            name="文件夹", stock=50, reference_price=10)
        prize3 = Prize.objects.create(
            name="杯子", stock=50, reference_price=20)
        prize4 = Prize.objects.create(
            name="院衫", stock=50, reference_price=50)
        prize5 = Prize.objects.create(
            name="棒球衫", stock=25, reference_price=100)
        prize6 = Prize.objects.create(
            name="卫衣", stock=25, reference_price=100)

        pool1 = Pool.objects.create(
            title="抽奖1：人人有奖", type=Pool.Type.LOTTERY, entry_time=2,
            start=datetime.now(),
        )
        pool2 = Pool.objects.create(
            title="抽奖2：人多于奖", type=Pool.Type.LOTTERY, entry_time=2,
            start=datetime.now(),
        )

        item1 = PoolItem.objects.create(
            pool=pool1, prize=prize1, origin_num=5)
        item2 = PoolItem.objects.create(
            pool=pool1, prize=prize2, origin_num=5)
        item3 = PoolItem.objects.create(
            pool=pool1, prize=prize3, origin_num=2)
        item4 = PoolItem.objects.create(
            pool=pool2, prize=prize1, origin_num=5)
        item5 = PoolItem.objects.create(
            pool=pool2, prize=prize5, origin_num=1)
        item6 = PoolItem.objects.create(
            pool=pool2, prize=prize6, origin_num=2)

        PoolRecord.objects.create(
            user=u10, pool=pool1, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u10, pool=pool1, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u1, pool=pool1, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u2, pool=pool1, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u3, pool=pool1, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u4, pool=pool1, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u5, pool=pool1, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u3, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u4, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u5, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u5, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u6, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u7, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u8, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u8, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u8, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u8, pool=pool2, status=PoolRecord.Status.LOTTERING)
        PoolRecord.objects.create(
            user=u8, pool=pool2, status=PoolRecord.Status.LOTTERING)

    def test_models(self):
        self.assertEqual(len(User.objects.all().values()), 11)
        Organization.objects.get(oname=YQP_ONAME)
        self.assertEqual(len(Prize.objects.all().values()), 6)
        self.assertEqual(len(Pool.objects.all().values()), 2)
        self.assertEqual(len(PoolItem.objects.all().values()), 6)
        self.assertEqual(len(PoolRecord.objects.filter(
            status=PoolRecord.Status.LOTTERING, 
            pool=Pool.objects.get(title="抽奖1：人人有奖")).values()), 7)
        self.assertEqual(len(PoolRecord.objects.filter(
            status=PoolRecord.Status.LOTTERING, 
            pool=Pool.objects.get(title="抽奖2：人多于奖")).values()), 11)

    def test_result1_item_and_record(self):  # 人人有奖
        pool = Pool.objects.get(title="抽奖1：人人有奖")
        run_lottery(pool.id)
        # 检查poolitem的consumed_num是否修改正确
        item1 = PoolItem.objects.get(prize__name="明信片", pool=pool.id)
        item2 = PoolItem.objects.get(prize__name="文件夹", pool=pool.id)
        item3 = PoolItem.objects.get(prize__name="杯子", pool=pool.id)
        self.assertEqual(
            12 - item1.consumed_num - item2.consumed_num - item3.consumed_num, 5)
        self.assertLessEqual(item1.consumed_num, item1.origin_num)
        self.assertLessEqual(item2.consumed_num, item2.origin_num)
        self.assertLessEqual(item3.consumed_num, item3.origin_num)
        # 检查poolrecord的status是否修改正确
        self.assertEqual(
            PoolRecord.objects.filter(
                status=PoolRecord.Status.UN_REDEEM, pool=pool).count(), 7)
        self.assertEqual(
            PoolRecord.objects.filter(
                status=PoolRecord.Status.NOT_LUCKY, pool=pool).count(), 0)
        # 检查poolrecord的prize是否修改正确
        self.assertLessEqual(
            PoolRecord.objects.filter(status=PoolRecord.Status.UN_REDEEM,
                                      pool=pool,
                                      prize__name="明信片").count(), 5)
        self.assertLessEqual(
            PoolRecord.objects.filter(status=PoolRecord.Status.UN_REDEEM,
                                      pool=pool,
                                      prize__name="文件夹").count(), 5)
        self.assertLessEqual(
            PoolRecord.objects.filter(status=PoolRecord.Status.UN_REDEEM,
                                      pool=pool,
                                      prize__name="杯子").count(), 2)
        self.assertEqual(
            PoolRecord.objects.filter(status=PoolRecord.Status.UN_REDEEM,
                                      pool=pool,
                                      prize__name__in=["明信片", "文件夹", "杯子"]).count(), 7)

    def test_result1_notification(self):  # 人人有奖
        pool = Pool.objects.get(title="抽奖1：人人有奖")
        run_lottery(pool.id)
        contents = list(Notification.objects.all(
        ).values_list("content", flat=True))
        # 检查获奖通知总数
        self.assertEqual(len(contents), sum(
            [1 if c[:2] == "恭喜" else 0 for c in contents]))
        # 检查获奖通知内容
        count_prize1 = sum([c.count("明信片") for c in contents])
        count_prize2 = sum([c.count("文件夹") for c in contents])
        count_prize3 = sum([c.count("杯子") for c in contents])
        self.assertLessEqual(count_prize1, 5)
        self.assertLessEqual(count_prize2, 5)
        self.assertLessEqual(count_prize3, 2)
        self.assertEqual(count_prize1+count_prize2+count_prize3, 7)

    def test_result2(self):  # 并非人人有奖
        pool = Pool.objects.get(title="抽奖2：人多于奖")
        run_lottery(pool.id)
        # 检查poolitem的consumed_num是否修改正确
        item1 = PoolItem.objects.get(prize__name="明信片", pool=pool.id)
        item5 = PoolItem.objects.get(prize__name="棒球衫", pool=pool.id)
        item6 = PoolItem.objects.get(prize__name="卫衣", pool=pool.id)
        self.assertEqual(
            item1.consumed_num, item1.origin_num)
        self.assertEqual(
            item5.consumed_num, item5.origin_num)
        self.assertEqual(
            item6.consumed_num, item6.origin_num)
        # 检查poolrecord的status是否修改正确
        self.assertEqual(
            PoolRecord.objects.filter(
                status=PoolRecord.Status.UN_REDEEM, pool=pool).count(), 8)
        self.assertEqual(
            PoolRecord.objects.filter(
                status=PoolRecord.Status.NOT_LUCKY, pool=pool).count(), 11-8)
        # 检查poolrecord的prize是否修改正确
        self.assertEqual(
            PoolRecord.objects.filter(status=PoolRecord.Status.UN_REDEEM,
                                      pool=pool,
                                      prize__name="明信片").count(), 5)
        self.assertEqual(
            PoolRecord.objects.filter(status=PoolRecord.Status.UN_REDEEM,
                                      pool=pool,
                                      prize__name="棒球衫").count(), 1)
        self.assertEqual(
            PoolRecord.objects.filter(status=PoolRecord.Status.UN_REDEEM,
                                      pool=pool,
                                      prize__name="卫衣").count(), 2)

    def test_result2_notification(self):  # 并非人人有奖
        pool = Pool.objects.get(title="抽奖2：人多于奖")
        run_lottery(pool.id)
        contents = list(Notification.objects.all(
        ).values_list("content", flat=True))
        # 检查获奖通知总数与未获奖通知总数
        count_winner = sum([1 if c[:2] == "恭喜" else 0 for c in contents])
        count_loser = sum([1 if c[:3] == "很抱歉" else 0 for c in contents])
        self.assertEqual(len(contents), count_loser+count_winner)
        self.assertLessEqual(count_winner, 8)
        # 检查获奖通知内容
        count_prize1 = sum([c.count("明信片") for c in contents])
        count_prize5 = sum([c.count("棒球衫") for c in contents])
        count_prize6 = sum([c.count("卫衣") for c in contents])
        self.assertEqual(count_prize1, 5)
        self.assertEqual(count_prize5, 1)
        self.assertEqual(count_prize6, 2)
