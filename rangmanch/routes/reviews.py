from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from models import Review, ReviewCreate, ReviewRead, ReviewUpdate
from database import get_session

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("/", response_model=ReviewRead)
async def create_review(review: ReviewCreate, session: Session = Depends(get_session)):
    db_review = Review(**review.model_dump())
    session.add(db_review)
    session.commit()
    session.refresh(db_review)
    return db_review


@router.get("/", response_model=list[ReviewRead])
async def list_reviews(
    play_name: str | None = Query(
        None, description="Filter reviews by play name"),
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(
            10, ge=1, le=50, description="Maximum number of records to return"),
        session: Session = Depends(get_session)
):
    query = select(Review)
    if play_name:
        query = query.where(Review.play_name == play_name)
    query = query.offset(skip).limit(limit)
    reviews = session.exec(query).all()
    return reviews


@router.get("/average-rating/{play_name}", response_model=dict)
async def average_rating(
    play_name: str,
    session: Session = Depends(get_session)
):
    avg_rating_query = select(func.avg(Review.rating)).where(
        Review.play_name == play_name)
    result = session.exec(avg_rating_query).first()
    avg_rating, total_reviews = result
    if total_reviews == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No reviews found for this play: {play_name}"
        )
    return {
        "play_name": play_name,
        "average_rating": round(avg_rating, 2),
        "total_reviews": total_reviews
    }


@router.get("/{review_id}", response_model=ReviewRead)
async def get_review(review_id: int, session: Session = Depends(get_session)):
    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(
            status_code=404, detail=f"Review with ID {review_id} not found")
    return review


@router.patch("/{review_id}", response_model=ReviewRead)
async def update_review(review_id: int, review_update: ReviewUpdate, session: Session = Depends(get_session)):
    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(
            status_code=404, detail=f"Review with ID {review_id} not found")

    for key, value in review_update.model_dump(exclude_unset=True).items():
        setattr(review, key, value)

    session.add(review)
    session.commit()
    session.refresh(review)
    return review


@router.delete("/{review_id}", response_model=dict)
async def delete_review(review_id: int, session: Session = Depends(get_session)):

    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(
            status_code=404, detail=f"Review with ID {review_id} not found")
    session.delete(review)
    session.commit()
    return {"message": f"Review with ID {review_id} has been deleted"}
