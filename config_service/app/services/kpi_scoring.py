from app.models.kpi_scoring import KPIScoring


class KPIScoringService:

    def __init__(self, scoring_repo):
        self.scoring_repo = scoring_repo

    async def replace_question_scoring(self, question_id, scores: list, user_id):
        """
        scores = [score1, score2, score3, score4, score5]
        """

        if len(scores) != 5:
            raise Exception("Exactly 5 scores required")

        await self.scoring_repo.delete_by_question(question_id)

        for i, score in enumerate(scores, start=1):
            scoring = KPIScoring(
                question_id=question_id,
                option_number=i,
                score=int(score),
                created_by=user_id,
                updated_by=user_id
            )
            await self.scoring_repo.create(scoring)
