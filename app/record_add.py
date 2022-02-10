import numpy
from app.models import (
    NaturalPerson,
    CourseRecord,
    Semester,
    Course
)
# needed: pip install openpyxl

# 标准格式 ：  (*.xlsx)
# 学号 | 姓名 | 学年 | 学期 | 课程名 | 参与次数 | 总学时
#  **     **    **     **      **        **       **
#  **     **    **     **      **        **       **
#  **     **    **     **      **        **       **
#  **     **    **     **      **        **       **
#  **     **    **     **      **        **       **
#  **     **    **     **      **        **       **

def CheckGetinFile(df):
    '''
    检查文件合法性
    '''
    height, weight = df.shape
    if weight != 7 or height <= 0:
        return 0
    for i in range(height):
        if (  
            type(df.iloc[i, 0]) != numpy.int64 or\
            type(df.iloc[i, 1]) != str or\
            type(df.iloc[i, 2]) != numpy.int64 or\
            type(df.iloc[i, 3]) != str or\
            type(df.iloc[i, 4]) != str or\
            type(df.iloc[i, 5]) != numpy.int64 or\
            type(df.iloc[i, 6]) != numpy.int64 
        ): return 1
    return -1

def add_courecord_byweb(list):
    add_courecord(list)


def add_courecord_byfile(df):
    '''
    通过文件添加学时记录
    '''    
    height, width = df.shape
    for i in range(height):
        
        get_stuID = df.iloc[i, 0]
        get_stuNAME = df.iloc[i, 1]
        get_classyear = df.iloc[i, 2]
        get_classSeme = df.iloc[i, 3]
        get_className = df.iloc[i, 4]
        get_times = df.iloc[i, 5]
        get_hours = df.iloc[i, 6]
        add_courecord([get_stuID,get_stuNAME,get_classyear,get_classSeme,get_className,get_times,get_hours])
        print([get_stuID,get_stuNAME,get_classyear,get_classSeme,get_className,get_times,get_hours])

def add_courecord(data_list):
    '''
    添加学时记录
    '''
    #TODO: 异常查找，重复查找
    course_found = False
    [get_stuID,get_stuNAME,get_classyear,get_classSeme,get_className,get_times,get_hours]=data_list

    if get_classSeme == u'秋季' or get_classSeme == u'秋':
        get_classSeme = 'Fall'
    elif get_classSeme == u'春季' or get_classSeme == u'春':
        get_classSeme = 'Spring'

    person_get = NaturalPerson.objects.filter(
        person_id__username = str(get_stuID),
        name = get_stuNAME
    )
    course_get = Course.objects.filter(
        name = get_className,
        year = get_classyear,
        semester = get_classSeme,
    )       

    if not person_get.exists() : 
        return 1
    if  course_get.exists():  #查找到了相应course
        course_found = True
    record_search = CourseRecord.objects.filter(
        person__person_id__username = str(get_stuID),
        person__name = get_stuNAME,
        year = get_classyear,
        semester = Semester.get(get_classSeme),
    )                         

    record_search_course = record_search.filter(course__name= get_className,)
    record_search_extra = record_search.filter(extra_name = get_className,)

    if (not record_search_course.exists()) and (not record_search_extra.exists()):
        newrecord = CourseRecord.objects.create(
            person = person_get[0],
            extra_name = get_className,
            attend_times = get_times,
            total_hours = get_hours,
            year = get_classyear,
            semester = Semester.get(get_classSeme),
        )
        if course_found: 
            newrecord.course = course_get[0] 
            newrecord.save()
            
    elif record_search_course.exists():
        record_search_course.update(
            attend_times = get_times, 
            total_hours = get_hours
        )
    else:
        record_search_extra.update(
            attend_times = get_times, 
            total_hours = get_hours
        )

    return 0