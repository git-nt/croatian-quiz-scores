from flask import Flask, request, render_template
import pandas as pd
import os 

# Load the Excel file and prepare data
file = os.path.join(os.path.dirname(__file__), 'wqc_scores.xlsx')  
xl = pd.read_excel(file, sheet_name=None)
sheets = sorted(xl.keys())

# Collect all unique player names
def get_all_players():
    players = set()
    for sheet in sheets:
        if 'WQC' in sheet:
            df = xl[sheet]
            players.update(df['Player'].dropna().unique())
    return sorted(players)

player_names = get_all_players()

# Define get_player_stats function
def get_player_stats(player):
    # Define possible genre column variants
    genre_map = {
        'Culture': ['CUL', 'Clt', 'Culture', 'CUL', 'CLT', 'Cult'],
        'Entertainment': ['ENT', 'Ent', 'Enter', 'ENT'],
        'History': ['HIS', 'Hst', 'Hist', 'HIS', 'HST', 'History', 'Histor'],
        'Media': ['MED', 'Med', 'Media', 'MED'],
        'Lifestyle': ['LIF', 'Lfs', 'Life', 'LFS', 'Lifest'],
        'Science': ['SCI', 'Sci', 'Scie', 'Scien'],
        'Sport & Games': ['SPO', 'Spt', 'Sports', 'Sport', 'SPT'],
        'World': ['WOR', 'Wld', 'World', 'WLD']
    }
    # Use three-letter abbreviations for headers
    columns = ['Quiz', 'Rnk', 'Tot', 'Cul', 'Ent', 'His', 'Med', 'Lif', 'Sci', 'Spt', 'Wor']
    output = pd.DataFrame(columns=columns)

    row = 0
    for sheet in sheets:
        if 'WQC' in sheet:
            df = xl[sheet]
            try:
                player_row = df[df['Player'] == player]
                if player_row.empty:
                    continue
                rank = int(player_row[['Rank', 'SCORE']].iloc[0]['Rank'])
                score = int(player_row[['Rank', 'SCORE']].iloc[0]['SCORE'])
                genre_scores = []
                # Map genre order to abbreviations
                genre_abbrs = ['Cul', 'Ent', 'His', 'Med', 'Lif', 'Sci', 'Spt', 'Wor']
                for abbr, (genre, variants) in zip(genre_abbrs, genre_map.items()):
                    found = None
                    genre_rank = None
                    for v in variants:
                        if v in df.columns:
                            # Get all scores for this genre in this year
                            genre_scores_all = df[v].dropna().astype(int)
                            # Sort descending, get ranks (1 = highest)
                            genre_scores_sorted = genre_scores_all.sort_values(ascending=False).reset_index(drop=True)
                            # Get this player's score
                            val = player_row.iloc[0][v]
                            if pd.notnull(val):
                                try:
                                    found = int(val)
                                    # Find all indices where score matches (handle ties)
                                    ranks = genre_scores_sorted[genre_scores_sorted == found].index
                                    if len(ranks) > 0:
                                        genre_rank = ranks[0] + 1  # 1-based
                                except Exception:
                                    found = None
                            break
                    if found is not None and genre_rank is not None:
                        genre_scores.append(f"{found} (#{genre_rank})")
                    elif found is not None:
                        genre_scores.append(str(found))
                    else:
                        genre_scores.append("")
                output.loc[row] = [sheet, rank, score] + genre_scores
                row += 1
            except Exception as e:
                pass
    return output

# Initialize Flask app
app = Flask(__name__)

# Define a route to display the form
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        player_name = request.form['player']
        stats_df = get_player_stats(player_name)
        # Style the DataFrame for HTML rendering
        styled = stats_df.style.set_table_attributes(
            'class="centered-table" style="margin-left:auto;margin-right:auto;table-layout:auto;width:100%;"'
        ).set_properties(
            **{'text-align': 'center', 'padding': '2px', 'font-size': '13px', 'min-width': '90px'}
        ).set_table_styles([
            {'selector': 'th', 'props': [('text-align', 'center'), ('background-color', '#4a90e2'), ('color', 'white'), ('font-weight', 'bold'), ('padding', '2px'), ('font-size', '13px'), ('min-width', '90px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('background-color', '#f9f9f9'), ('padding', '2px'), ('font-size', '13px'), ('min-width', '90px')]},
            {'selector': 'tr:nth-child(even) td', 'props': [('background-color', '#e8f1fb')]},
        ])
        results_html = styled.to_html(escape=False, index=False)
        return render_template('index.html', results_html=results_html, player_name=player_name, players=player_names)
    return render_template('index.html', results_html=None, players=player_names)

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
