# 清除一周前的预约
def clear_appointments(request):
    appoints_to_delete = Appoint.objects.filter(Afinish__lte=datetime.now()-timedelta(days=7))
    try:
        with transaction.atomic():
            appoints_to_delete.delete()
    except Exception as e:
        return JsonResponse(
                {'statusInfo': {
                    'message': '删除时出现错误',
                    'detail': str(e)
                }},
                status=400)
    return JsonResponse({'message':'已正常删除一周前的所有预约'}, status=200)