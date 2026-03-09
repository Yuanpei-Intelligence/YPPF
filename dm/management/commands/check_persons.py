import pandas as pd
import os
import sys
from django.core.management.base import BaseCommand
from django.db import transaction
from app.models import NaturalPerson, User

# 自定义异常，用于在用户拒绝确认时回滚事务


class DryRunRollback(Exception):
    pass

class Command(BaseCommand):
    help = '检查并修正数据库人员状态，支持Diff导出与事务回滚'

    def add_arguments(self, parser):
        parser.add_argument('excel_path', type=str,
                            help='Excel文件的路径（需包含列：姓名、学号、状态）')
        parser.add_argument(
            '--no-confirm',
            action='store_true',
            help='无需确认直接执行'
        )

    def handle(self, *args, **options):
        excel_path = options['excel_path']
        skip_confirm = options['no_confirm']

        # ================= 配置区域 =================
        # 1. 状态映射配置：根据 app/models.py 中的定义进行完善
        # 依据：models.py 中 GraduateStatus 的定义，未来可更新更多状态
        STATUS_MAP = {
            "在校": NaturalPerson.GraduateStatus.UNDERGRADUATED,
            "毕业": NaturalPerson.GraduateStatus.GRADUATED,
        }

        # 2. 读取 Excel
        if not os.path.exists(excel_path):
            self.stderr.write(self.style.ERROR(f"文件不存在: {excel_path}"))
            return

        try:
            df = pd.read_excel(excel_path, dtype={'学号': str})
        except Exception as e:
            self.stderr.write(f"读取 Excel 失败: {e}")
            return

        # 3. 初始化统计与记录
        diff_records = []
        stats = {
            "total": len(df),
            "processed": 0,
            "updated": 0,
            "not_found": 0,
            "unknown_status": 0,
            "unchanged": 0
        }

        self.stdout.write(self.style.NOTICE(
            f">>> 正在读取 {len(df)} 条数据，准备计算差异..."))
        self.stdout.write(self.style.NOTICE(">>> 数据库连接已建立，事务开启中..."))

        # 4. 开启原子事务
        try:
            with transaction.atomic():
                for index, row in df.iterrows():
                    stats["processed"] += 1

                    # 数据清洗
                    name = str(row.get('姓名', '')).strip()
                    stu_id = str(row.get('学号', '')).strip()
                    excel_status_str = str(row.get('状态', '')).strip()

                    if not name or not stu_id:
                        self.stdout.write(self.style.WARNING(
                            f" [跳过] 第{index+2}行数据不完整"))
                        continue

                    # A. 查找人员
                    # 优先使用学号查找，双重校验姓名
                    person = NaturalPerson.objects.filter(
                        person_id__username=stu_id).first()

                    if not person:
                        # 尝试用姓名查找
                        self.stdout.write(self.style.WARNING(
                            f" [缺失] 第{index+2}行: 学号 {stu_id} 未找到用户"))
                        stats["not_found"] += 1
                        continue

                    if person.name != name:
                        self.stdout.write(self.style.WARNING(
                            f" [疑义] 第{index+2}行: 学号 {stu_id} 数据库名为 '{person.name}'，Excel名为 '{name}'。以学号为准继续。"))

                    # B. 获取旧状态
                    old_status_code = person.status
                    old_status_str = person.get_status_display()

                    # C. 目标状态转换
                    target_code = STATUS_MAP.get(excel_status_str)

                    if target_code is None:
                        self.stdout.write(self.style.ERROR(
                            f" [未知状态] 第{index+2}行: '{excel_status_str}' 不在映射表中"))
                        stats["unknown_status"] += 1
                        continue

                    # D. 比对状态
                    if old_status_code == target_code:
                        stats["unchanged"] += 1
                        continue

                    # E. 模拟修改
                    # 此时修改仅在事务内存中
                    person.status = target_code
                    person.save(update_fields=['status'])

                    stats["updated"] += 1

                    # F. 记录差异
                    diff_records.append({
                        "行号": index + 2,
                        "学号": stu_id,
                        "姓名": person.name,
                        "原状态": old_status_str,
                        "新状态": excel_status_str,
                    })

                # ================= 确认环节 =================

                self.stdout.write("\n" + "="*50)
                self.stdout.write(" 处理统计：")
                self.stdout.write(f" 总行数: {stats['total']}")
                self.stdout.write(f" 需更新: {stats['updated']} (差异)")
                self.stdout.write(f" 无变化: {stats['unchanged']}")
                self.stdout.write(f" 未找到: {stats['not_found']}")
                self.stdout.write("="*50)

                if not diff_records:
                    self.stdout.write(self.style.SUCCESS("🎉 所有数据与数据库一致，无需变更。"))
                    return  # 正常退出，事务会自动提交，但因为没改数据所以无所谓

                # 导出 Diff 报表到 raw_data
                output_dir = "raw_data"
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)

                diff_file = os.path.join(output_dir, "status_diff_report.xlsx")
                pd.DataFrame(diff_records).to_excel(diff_file, index=False)

                self.stdout.write(self.style.SUCCESS(
                    f"\n📄 详细差异表已生成: {diff_file}"))
                self.stdout.write(self.style.SUCCESS(
                    "请务必检查 Excel 中的变更是否符合预期！"))

                # 终端预览前 10 条
                self.stdout.write("\n变更预览 (Top 10):")
                print(f"{'姓名':<10} | {'学号':<12} | {'原状态':<10} -> {'新状态'}")
                print("-" * 50)
                for rec in diff_records[:10]:
                    print(
                        f"{rec['姓名']:<10} | {rec['学号']:<12} | {rec['原状态']:<10} -> {rec['新状态']}")

                if len(diff_records) > 10:
                    print(f"... 以及其他 {len(diff_records)-10} 条 ...")

                # 最终确认逻辑
                if skip_confirm:
                    self.stdout.write(self.style.WARNING(
                        "\n>>> 参数指定跳过确认，正在提交事务..."))
                else:
                    self.stdout.write(self.style.ERROR(
                        "\n⚠️  警告：该操作将修改线上数据库！"))
                    confirm = input("请输入 'YES' (大写) 确认提交，输入其他任意内容回滚: ")

                    if confirm != 'YES':
                        raise DryRunRollback("用户取消操作")

        except DryRunRollback:
            self.stdout.write(self.style.SUCCESS(
                "\n🛑 操作已取消，数据库状态已回滚，未发生任何变更。"))

        except Exception as e:
            # 捕获其他未知代码错误，打印堆栈并回滚
            import traceback
            traceback.print_exc()
            self.stdout.write(self.style.ERROR(f"\n❌ 发生程序错误: {e}"))
            self.stdout.write(self.style.ERROR("事务已自动回滚。"))
            sys.exit(1)

        else:
            # 只有当 try 块成功执行到底（即用户输入YES且无报错）时执行
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ 事务提交成功！已更新 {stats['updated']} 条人员状态。"))
