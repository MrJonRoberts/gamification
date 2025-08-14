from app import create_app, db
from app.models import User, Course, Enrollment, Badge, BadgeGrant, Award, AwardBadge, PointLedger

app = create_app()

# Optional: shell context
@app.shell_context_processor
def make_shell_context():
    return dict(db=db, User=User, Course=Course, Enrollment=Enrollment,
                Badge=Badge, BadgeGrant=BadgeGrant, Award=Award, AwardBadge=AwardBadge,
                PointLedger=PointLedger)

if __name__ == "__main__":
    app.run()
