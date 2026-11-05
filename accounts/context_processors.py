def profile(request):
    return {"profile": getattr(request, "profile", None)}
