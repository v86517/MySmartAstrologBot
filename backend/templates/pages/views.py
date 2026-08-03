from django.shortcuts import render

def privacy_policy(request):
    return render(request, 'pages/privacy_policy.html')

def consent(request):
    return render(request, 'pages/consent.html')