from app.views_dependency import ProfileTemplateView
from utils.global_messages import transfer_message_context
from yp_library.utils import (
    get_readers_by_user,
    search_books,
    get_query_dict,
    get_lendinfo_by_readers,
    get_library_activity, 
    get_recommended_or_newest_books, 
)
from yp_library.config import library_conf

DISPLAY_ACTIVITY_NUM = 3 # 首页展示的书房活动数量
DISPLAY_RECOMMENDATION_NUM = 5 # 首页展示的推荐书目数量
# DISPLAY_NEW_BOOK_NUM = 5 # 首页展示的新入馆书目数量


class WelcomeView(ProfileTemplateView):
    """
    书房首页，提供近期活动、随机推荐、开馆时间；
    首页的查询功能应该可以通过前端转到search页面，这里未做处理
    """

    template_name = "yp_library/welcome.html"
    page_name = "元培书房"
    need_prepare = False

    def get(self):
        # 借阅记录
        try:
            readers = get_readers_by_user(self.request.user)
        except AssertionError as e:
            records_list = []
        else:
            unreturned_records_list, returned_records_list = get_lendinfo_by_readers(readers)
            records_list = unreturned_records_list + returned_records_list

        transfer_message_context(self.request.GET, self.extra_context,
                                 normalize=True)
        self.extra_context.update({
            "activities": get_library_activity(num=DISPLAY_ACTIVITY_NUM),
            "opening_time_start": library_conf.start_time,
            "opening_time_end": library_conf.end_time,
            "records_list": records_list,
            "recommendation": get_recommended_or_newest_books(
                        num=DISPLAY_RECOMMENDATION_NUM, newest=False),
        })
        return self.render()


class SearchView(ProfileTemplateView):
    """
    图书检索页面
    """

    template_name = "yp_library/search.html"
    page_name = "书籍搜索结果"
    need_prepare = False

    def get(self):
        transfer_message_context(self.request.GET, self.extra_context,
                                 normalize=True)
        return self.render()

    def post(self):
        self.extra_context.update({
            "search_results_list": search_books(**get_query_dict(self.request.POST)),
        })
        return self.render()
