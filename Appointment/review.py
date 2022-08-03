def review(request):
    if request.method=="GET":
        try:
            Lid=request.GET.get("Lid")
            if Lid:
                target_appoint=LongTermAppoint.objects.get(pk=Lid)
        except:
            return redirect(reverse("Appointment:review"))

        all_instances={
            "reviewing":LongTermAppoint.objects.filter(status=LongTermAppoint.Status.REVIEWING),
            "reviewed":LongTermAppoint.objects.filter(Q(status=LongTermAppoint.Status.APPROVED)|Q(status=LongTermAppoint.Status.REJECTED))
        }
        if Lid and target_appoint:
            longterm_appoint={
                "Lid":Lid,
                "room":f"{target_appoint.appoint.Room.Rid} {target_appoint.appoint.Room.Rtitle}",
                "organization":target_appoint.org.name,
                "week":target_appoint.appoint.Astart.strftime("%A"),
                "date":target_appoint.appoint.Astart.strftime("%m月%d日"),
                "start": target_appoint.appoint.Astart.strftime("%I:%M %p"),
                "finish": target_appoint.appoint.Afinish.strftime("%I:%M %p"),
                "times":target_appoint.times,
                "interval":target_appoint.interval,
                "usage":target_appoint.appoint.Ausage,
                "status":target_appoint.get_status_display(),
                # "reason":target_appoint.reason
            }
        return render(request, 'Appointment/review.html', locals())

    if request.method=="POST":
        post_data = json.loads(request.body.decode("utf-8"))
        Lid=post_data["Lid"]
        operation=post_data["operation"]
        # 处理预约状态
        if operation == "approve":
            target_appoint=LongTermAppoint.objects.get(pk=Lid)
            target_appoint.status=LongTermAppoint.Status.APPROVED

            target_appoint.save()
            return JsonResponse({"status":"ok"})

        elif operation == "refect":
            pass


        target_appoint=LongTermAppoint.objects.get(pk=Lid)
        target_appoint.status=LongTermAppoint.Status.APPROVED
        target_appoint.save()
        return JsonResponse({"status":"ok"})
        
