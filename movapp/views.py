from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
import json
from .data_loader import movie_data_loader

def home(request):
    """Homepage view for the Movie Recommendation System"""
    if request.method == 'POST':
        try:
            # Get selected movies from form
            selected_movies = request.POST.getlist('selected_movies')
            
            if len(selected_movies) < 3:
                return render(request, 'movapp/home.html', {
                    'error': 'Please select at least 3 movies to get recommendations.'
                })
            
            # Get filter parameters from form
            filters = {
                'genres': request.POST.getlist('genres'),
                'year_min': request.POST.get('year_min'),
                'year_max': request.POST.get('year_max'),
                'min_rating': request.POST.get('min_rating'),
                'sort_by': request.POST.get('sort_by', 'rating')
            }
            
            # Clean empty values
            filters = {k: v for k, v in filters.items() if v and v != '0'}
            print(f"🔧 Received filters: {filters}")
            
            # Generate ALL available recommendations (not limited to 20)
            # This will get all possible recommendations based on user preferences
            all_recommendations = movie_data_loader.get_filtered_recommendations(
                selected_movies, filters, num_recommendations=1000  # Get many recommendations
            )
            
            print(f"🎬 Generated {len(all_recommendations)} total recommendations")
            
            # Show first 10 recommendations initially
            initial_recommendations = all_recommendations[:10]
            
            # Calculate statistics for the insights panel
            total_recommendations = len(all_recommendations)
            avg_confidence = 0
            if all_recommendations:
                confidence_scores = [rec.get('confidence_score', 0) for rec in all_recommendations if rec.get('confidence_score')]
                if confidence_scores:
                    avg_confidence = round(sum(confidence_scores) / len(confidence_scores), 1)
            
            return render(request, 'movapp/results.html', {
                'selected_movies': selected_movies,
                'recommendations': initial_recommendations,
                'total_recommendations': total_recommendations,
                'avg_confidence': avg_confidence,
                'current_page': 1,
                'has_more': total_recommendations > 10,
                'applied_filters': filters
            })
            
        except Exception as e:
            return render(request, 'movapp/home.html', {
                'error': f'An error occurred: {str(e)}'
            })
    
    return render(request, 'movapp/home.html')

def load_more_recommendations(request):
    """AJAX endpoint for loading more recommendations (infinite scroll)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            selected_movies = data.get('selected_movies', [])
            filters = data.get('filters', {})
            page = data.get('page', 1)
            
            if len(selected_movies) < 3:
                return JsonResponse({
                    'success': False,
                    'error': 'Please select at least 3 movies'
                })
            
            # FIX: Clean and validate filter data before processing
            cleaned_filters = {}
            
            # Handle genres (list of strings)
            if 'genres' in filters and filters['genres']:
                if isinstance(filters['genres'], list):
                    cleaned_filters['genres'] = filters['genres']
                else:
                    cleaned_filters['genres'] = [filters['genres']]
            
            # Handle year_min (single string/int)
            if 'year_min' in filters and filters['year_min']:
                try:
                    if isinstance(filters['year_min'], list):
                        cleaned_filters['year_min'] = filters['year_min'][0]
                    else:
                        cleaned_filters['year_min'] = filters['year_min']
                except (ValueError, IndexError):
                    pass
            
            # Handle year_max (single string/int)
            if 'year_max' in filters and filters['year_max']:
                try:
                    if isinstance(filters['year_max'], list):
                        cleaned_filters['year_max'] = filters['year_max'][0]
                    else:
                        cleaned_filters['year_max'] = filters['year_max']
                except (ValueError, IndexError):
                    pass
            
            # Handle min_rating (single string/float)
            if 'min_rating' in filters and filters['min_rating']:
                try:
                    if isinstance(filters['min_rating'], list):
                        cleaned_filters['min_rating'] = filters['min_rating'][0]
                    else:
                        cleaned_filters['min_rating'] = filters['min_rating']
                except (ValueError, IndexError):
                    pass
            
            # Handle sort_by (single string)
            if 'sort_by' in filters and filters['sort_by']:
                if isinstance(filters['sort_by'], list):
                    cleaned_filters['sort_by'] = filters['sort_by'][0]
                else:
                    cleaned_filters['sort_by'] = filters['sort_by']
            
            print(f"🔧 Original filters: {filters}")
            print(f"🔧 Cleaned filters: {cleaned_filters}")
            
            # Generate all recommendations again (will be cached if using cache)
            all_recommendations = movie_data_loader.get_filtered_recommendations(
                selected_movies, cleaned_filters, num_recommendations=1000
            )
            
            # Calculate pagination
            items_per_page = 10
            start_index = (page - 1) * items_per_page
            end_index = start_index + items_per_page
            
            # Get the next batch of recommendations
            next_batch = all_recommendations[start_index:end_index]
            
            # Check if there are more recommendations after this batch
            has_more = end_index < len(all_recommendations)
            
            print(f"📄 Page {page}: Returning {len(next_batch)} recommendations, has_more: {has_more}")
            
            return JsonResponse({
                'success': True,
                'recommendations': next_batch,
                'has_more': has_more,
                'current_page': page,
                'total_recommendations': len(all_recommendations)
            })
            
        except Exception as e:
            print(f"❌ Error in load_more_recommendations: {str(e)}")
            import traceback
            traceback.print_exc()  # This will show the full error trace
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


def get_movie_poster(request):
    """
    NEW: AJAX endpoint for lazy loading individual movie posters
    This eliminates the long loading screen by fetching posters on-demand
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            movie_title = data.get('title', '')
            movie_genres = data.get('genres', [])
            
            if not movie_title:
                return JsonResponse({
                    'success': False,
                    'error': 'Movie title is required'
                })
            
            print(f"🎨 Lazy loading poster for: {movie_title}")
            
            # Use the data loader to fetch the real poster
            poster_url = movie_data_loader.get_poster_for_movie(movie_title, movie_genres)
            
            return JsonResponse({
                'success': True,
                'title': movie_title,
                'poster_url': poster_url
            })
            
        except Exception as e:
            print(f"❌ Error fetching poster for {movie_title}: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def search_movies(request):
    """AJAX endpoint for movie search with filter support"""
    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'movies': []})
    
    # Get filter parameters from request
    filters = {
        'genres': request.GET.getlist('genres'),
        'year_min': request.GET.get('year_min'),
        'year_max': request.GET.get('year_max'),
        'min_rating': request.GET.get('min_rating')
    }
    
    # Clean empty values
    filters = {k: v for k, v in filters.items() if v and v != '0'}
    
    matches = movie_data_loader.search_movies(query, filters, limit=10)
    return JsonResponse({'movies': matches})

def filter_recommendations(request):
    """AJAX endpoint for live filtering of recommendations"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            selected_movies = data.get('selected_movies', [])
            filters = data.get('filters', {})
            
            if len(selected_movies) < 3:
                return JsonResponse({
                    'success': False,
                    'error': 'Please select at least 3 movies'
                })
            
            # Generate filtered recommendations
            recommendations = movie_data_loader.get_filtered_recommendations(
                selected_movies, filters, 10
            )
            
            return JsonResponse({
                'success': True,
                'recommendations': recommendations,
                'count': len(recommendations)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})
