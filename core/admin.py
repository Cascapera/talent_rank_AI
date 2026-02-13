from django.contrib import admin

from .models import Job, Candidate, CandidateJob, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'plan_expires_at', 'phone', 'cpf')
    list_editable = ('plan', 'plan_expires_at')
    list_filter = ('plan',)
    search_fields = ('user__username', 'user__email', 'phone', 'cpf')
    date_hierarchy = 'plan_expires_at'


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'status',
        'seniority',
        'location',
        'department',
        'stack',
        'contract_type',
        'boolean_search',
        'created_at',
    )
    list_filter = ('status', 'seniority', 'location', 'department', 'stack', 'contract_type')
    search_fields = ('title', 'department', 'location', 'seniority', 'stack', 'contract_type', 'boolean_search')


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'current_title',
        'current_company',
        'location',
        'seniority',
        'experience_time',
        'average_tenure',
        'has_resume_pdf',
        'ready_at',
        'updated_at',
    )
    list_filter = ('seniority', 'location')
    search_fields = (
        'name',
        'current_title',
        'current_company',
        'location',
        'linkedin_url',
        'summary',
        'skills',
        'technologies',
        'languages',
        'certifications',
    )

    def has_resume_pdf(self, obj):
        return bool(obj.resume_pdf)

    has_resume_pdf.boolean = True
    has_resume_pdf.short_description = "Tem PDF"


@admin.register(CandidateJob)
class CandidateJobAdmin(admin.ModelAdmin):
    list_display = (
        'job',
        'candidate',
        'pipeline_status',
        'ready_at',
        'updated_at',
    )
    list_filter = ('pipeline_status', 'ready_at', 'job')
    search_fields = ('candidate__name', 'candidate__linkedin_url', 'job__title')
